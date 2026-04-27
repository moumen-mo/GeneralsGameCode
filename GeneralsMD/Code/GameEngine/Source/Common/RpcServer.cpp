#include "PreRTS.h"
#include "Common/RpcServer.h"
#include "Common/MessageStream.h"
#include "GameLogic/GameLogic.h"
#include "GameLogic/Object.h"
#include "Common/PlayerList.h"
#include "Common/Player.h"
#include "Common/Thing.h"
#include "Common/ThingTemplate.h"

#include <winsock2.h>
#include <ws2tcpip.h>

#include <atomic>
#include <cmath>
#include <cstring>
#include <deque>
#include <iomanip>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace
{
    enum class JsonType
    {
        Null,
        Boolean,
        Number,
        String,
        Array,
        Object
    };

    struct JsonValue
    {
        JsonType type;
        bool booleanValue;
        double numberValue;
        std::string stringValue;
        std::vector<JsonValue> arrayValue;
        std::map<std::string, JsonValue> objectValue;

        JsonValue() : type(JsonType::Null), booleanValue(false), numberValue(0.0) {}
        JsonValue(bool value) : type(JsonType::Boolean), booleanValue(value), numberValue(0.0) {}
        JsonValue(double value) : type(JsonType::Number), booleanValue(false), numberValue(value) {}
        JsonValue(const std::string &value) : type(JsonType::String), booleanValue(false), numberValue(0.0), stringValue(value) {}
        JsonValue(const char *value) : type(JsonType::String), booleanValue(false), numberValue(0.0), stringValue(value) {}

        bool isObject() const { return type == JsonType::Object; }
        bool isArray() const { return type == JsonType::Array; }
        bool isString() const { return type == JsonType::String; }
        bool isNumber() const { return type == JsonType::Number; }
        bool isBoolean() const { return type == JsonType::Boolean; }
        bool isNull() const { return type == JsonType::Null; }

        const JsonValue *findMember(const std::string &key) const
        {
            std::map<std::string, JsonValue>::const_iterator it = objectValue.find(key);
            return it == objectValue.end() ? nullptr : &it->second;
        }

        bool getString(std::string &out) const
        {
            if (!isString())
                return false;
            out = stringValue;
            return true;
        }

        bool getBoolean(bool &out) const
        {
            if (!isBoolean())
                return false;
            out = booleanValue;
            return true;
        }

        bool getNumber(double &out) const
        {
            if (!isNumber())
                return false;
            out = numberValue;
            return true;
        }

        bool getInt(int &out) const
        {
            if (!isNumber())
                return false;
            double rounded = floor(numberValue + 0.5);
            if (fabs(numberValue - rounded) > 0.000001)
                return false;
            out = static_cast<int>(rounded);
            return true;
        }
    };

    static void skipWhitespace(const std::string &text, size_t &pos)
    {
        while (pos < text.size())
        {
            char c = text[pos];
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r')
                ++pos;
            else
                break;
        }
    }

    static bool parseHexDigit(char c, int &value)
    {
        if (c >= '0' && c <= '9')
            value = c - '0';
        else if (c >= 'a' && c <= 'f')
            value = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F')
            value = c - 'A' + 10;
        else
            return false;
        return true;
    }

    static bool parseUnicodeEscape(const std::string &text, size_t &pos, std::string &out)
    {
        if (pos + 4 > text.size())
            return false;

        unsigned int codepoint = 0;
        for (int i = 0; i < 4; ++i)
        {
            int digit;
            if (!parseHexDigit(text[pos + i], digit))
                return false;
            codepoint = (codepoint << 4) | digit;
        }

        pos += 4;

        if (codepoint < 0x80)
        {
            out.push_back(static_cast<char>(codepoint));
            return true;
        }

        if (codepoint < 0x800)
        {
            out.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
            out.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
            return true;
        }

        out.push_back(static_cast<char>(0xE0 | ((codepoint >> 12) & 0x0F)));
        out.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
        return true;
    }

    static bool parseString(const std::string &text, size_t &pos, std::string &out, std::string &error)
    {
        if (pos >= text.size() || text[pos] != '"')
        {
            error = "Expected string '\"'";
            return false;
        }

        ++pos;
        out.clear();

        while (pos < text.size())
        {
            char c = text[pos++];
            if (c == '"')
                return true;
            if (c == '\\')
            {
                if (pos >= text.size())
                {
                    error = "Unterminated escape sequence";
                    return false;
                }
                char escaped = text[pos++];
                switch (escaped)
                {
                    case '"': out.push_back('"'); break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    case 'b': out.push_back('\b'); break;
                    case 'f': out.push_back('\f'); break;
                    case 'n': out.push_back('\n'); break;
                    case 'r': out.push_back('\r'); break;
                    case 't': out.push_back('\t'); break;
                    case 'u':
                        if (!parseUnicodeEscape(text, pos, out))
                        {
                            error = "Invalid unicode escape";
                            return false;
                        }
                        break;
                    default:
                        error = "Invalid escape sequence";
                        return false;
                }
                continue;
            }
            if (static_cast<unsigned char>(c) < 0x20)
            {
                error = "Invalid control character in string";
                return false;
            }
            out.push_back(c);
        }

        error = "Unterminated string";
        return false;
    }

    static bool parseNumber(const std::string &text, size_t &pos, double &out, std::string &error)
    {
        size_t start = pos;
        if (pos < text.size() && (text[pos] == '-' || text[pos] == '+'))
            ++pos;

        bool hasDigits = false;
        while (pos < text.size() && isdigit(static_cast<unsigned char>(text[pos])))
        {
            ++pos;
            hasDigits = true;
        }

        if (pos < text.size() && text[pos] == '.')
        {
            ++pos;
            while (pos < text.size() && isdigit(static_cast<unsigned char>(text[pos])))
            {
                ++pos;
                hasDigits = true;
            }
        }

        if (!hasDigits)
        {
            error = "Invalid number";
            return false;
        }

        if (pos < text.size() && (text[pos] == 'e' || text[pos] == 'E'))
        {
            ++pos;
            if (pos < text.size() && (text[pos] == '+' || text[pos] == '-'))
                ++pos;
            bool exponentDigits = false;
            while (pos < text.size() && isdigit(static_cast<unsigned char>(text[pos])))
            {
                ++pos;
                exponentDigits = true;
            }
            if (!exponentDigits)
            {
                error = "Invalid number exponent";
                return false;
            }
        }

        std::string token = text.substr(start, pos - start);
        char *endPtr = nullptr;
        out = strtod(token.c_str(), &endPtr);
        if (endPtr != token.c_str() + token.size())
        {
            error = "Invalid number token";
            return false;
        }
        return true;
    }

    static bool parseValue(const std::string &text, size_t &pos, JsonValue &value, std::string &error);

    static bool parseArray(const std::string &text, size_t &pos, JsonValue &result, std::string &error)
    {
        if (pos >= text.size() || text[pos] != '[')
        {
            error = "Expected '[' for array";
            return false;
        }

        ++pos;
        result.type = JsonType::Array;
        result.arrayValue.clear();
        skipWhitespace(text, pos);

        if (pos < text.size() && text[pos] == ']')
        {
            ++pos;
            return true;
        }

        while (true)
        {
            JsonValue item;
            if (!parseValue(text, pos, item, error))
                return false;

            result.arrayValue.push_back(item);
            skipWhitespace(text, pos);

            if (pos < text.size() && text[pos] == ']')
            {
                ++pos;
                return true;
            }
            if (pos >= text.size() || text[pos] != ',')
            {
                error = "Expected ',' or ']' in array";
                return false;
            }
            ++pos;
            skipWhitespace(text, pos);
        }
    }

    static bool parseObject(const std::string &text, size_t &pos, JsonValue &result, std::string &error)
    {
        if (pos >= text.size() || text[pos] != '{')
        {
            error = "Expected '{' for object";
            return false;
        }

        ++pos;
        result.type = JsonType::Object;
        result.objectValue.clear();
        skipWhitespace(text, pos);

        if (pos < text.size() && text[pos] == '}')
        {
            ++pos;
            return true;
        }

        while (true)
        {
            std::string key;
            if (!parseString(text, pos, key, error))
                return false;

            skipWhitespace(text, pos);
            if (pos >= text.size() || text[pos] != ':')
            {
                error = "Expected ':' after object key";
                return false;
            }
            ++pos;
            skipWhitespace(text, pos);

            JsonValue value;
            if (!parseValue(text, pos, value, error))
                return false;

            result.objectValue[key] = value;
            skipWhitespace(text, pos);

            if (pos < text.size() && text[pos] == '}')
            {
                ++pos;
                return true;
            }
            if (pos >= text.size() || text[pos] != ',')
            {
                error = "Expected ',' or '}' in object";
                return false;
            }
            ++pos;
            skipWhitespace(text, pos);
        }
    }

    static bool parseValue(const std::string &text, size_t &pos, JsonValue &value, std::string &error)
    {
        skipWhitespace(text, pos);
        if (pos >= text.size())
        {
            error = "Unexpected end of input";
            return false;
        }

        char c = text[pos];
        if (c == '"')
        {
            std::string stringValue;
            if (!parseString(text, pos, stringValue, error))
                return false;
            value = JsonValue(stringValue);
            return true;
        }
        if (c == '{')
            return parseObject(text, pos, value, error);
        if (c == '[')
            return parseArray(text, pos, value, error);
        if (c == 't')
        {
            const char *token = "true";
            size_t tokenLen = 4;
            if (pos + tokenLen <= text.size() && text.compare(pos, tokenLen, token) == 0)
            {
                pos += tokenLen;
                value = JsonValue(true);
                return true;
            }
        }
        if (c == 'f')
        {
            const char *token = "false";
            size_t tokenLen = 5;
            if (pos + tokenLen <= text.size() && text.compare(pos, tokenLen, token) == 0)
            {
                pos += tokenLen;
                value = JsonValue(false);
                return true;
            }
        }
        if (c == 'n')
        {
            const char *token = "null";
            size_t tokenLen = 4;
            if (pos + tokenLen <= text.size() && text.compare(pos, tokenLen, token) == 0)
            {
                pos += tokenLen;
                value = JsonValue();
                return true;
            }
        }

        double numberValue = 0.0;
        if (parseNumber(text, pos, numberValue, error))
        {
            value = JsonValue(numberValue);
            return true;
        }

        if (error.empty())
            error = "Invalid JSON value";
        return false;
    }

    static bool parseJson(const std::string &text, JsonValue &result, std::string &error)
    {
        size_t pos = 0;
        if (!parseValue(text, pos, result, error))
            return false;
        skipWhitespace(text, pos);
        if (pos != text.size())
        {
            error = "Extra characters after JSON value";
            return false;
        }
        return true;
    }

    static void appendEscapedString(std::string &output, const std::string &value)
    {
        output.push_back('"');
        for (size_t i = 0; i < value.size(); ++i)
        {
            unsigned char c = static_cast<unsigned char>(value[i]);
            switch (c)
            {
                case '"': output += "\\\""; break;
                case '\\': output += "\\\\"; break;
                case '\b': output += "\\b"; break;
                case '\f': output += "\\f"; break;
                case '\n': output += "\\n"; break;
                case '\r': output += "\\r"; break;
                case '\t': output += "\\t"; break;
                default:
                    if (c < 0x20)
                    {
                        const char hexDigits[] = "0123456789abcdef";
                        output += "\\u00";
                        output.push_back(hexDigits[(c >> 4) & 0xF]);
                        output.push_back(hexDigits[c & 0xF]);
                    }
                    else
                    {
                        output.push_back(static_cast<char>(c));
                    }
                    break;
            }
        }
        output.push_back('"');
    }

    static std::string serializeJson(const JsonValue &value)
    {
        switch (value.type)
        {
            case JsonType::Null:
                return std::string("null");
            case JsonType::Boolean:
                return std::string(value.booleanValue ? "true" : "false");
            case JsonType::Number:
            {
                std::ostringstream oss;
                oss << std::setprecision(15) << value.numberValue;
                std::string token = oss.str();
                if (token.find('.') == std::string::npos && token.find('e') == std::string::npos && token.find('E') == std::string::npos)
                    token += ".0";
                return token;
            }
            case JsonType::String:
            {
                std::string escaped;
                appendEscapedString(escaped, value.stringValue);
                return escaped;
            }
            case JsonType::Array:
            {
                std::string result;
                result.push_back('[');
                for (size_t i = 0; i < value.arrayValue.size(); ++i)
                {
                    if (i)
                        result.push_back(',');
                    result += serializeJson(value.arrayValue[i]);
                }
                result.push_back(']');
                return result;
            }
            case JsonType::Object:
            {
                std::string result;
                result.push_back('{');
                bool first = true;
                for (std::map<std::string, JsonValue>::const_iterator it = value.objectValue.begin(); it != value.objectValue.end(); ++it)
                {
                    if (!first)
                        result.push_back(',');
                    first = false;
                    appendEscapedString(result, it->first);
                    result.push_back(':');
                    result += serializeJson(it->second);
                }
                result.push_back('}');
                return result;
            }
        }
        return std::string("null");
    }

    static JsonValue makeObject()
    {
        JsonValue object;
        object.type = JsonType::Object;
        return object;
    }

    static JsonValue makeArray()
    {
        JsonValue array;
        array.type = JsonType::Array;
        return array;
    }

    static JsonValue makeString(const std::string &value)
    {
        return JsonValue(value);
    }

    static JsonValue makeNumber(double value)
    {
        return JsonValue(value);
    }

    static JsonValue makeBoolean(bool value)
    {
        return JsonValue(value);
    }

    static JsonValue buildObjectJson(const Object *object)
    {
        JsonValue result = makeObject();
        result.objectValue["id"] = makeNumber(static_cast<double>(object->getID()));

        const ThingTemplate *tmpl = object->getTemplate();
        if (tmpl)
            result.objectValue["template_id"] = makeNumber(static_cast<double>(tmpl->getID()));

        const Coord3D *position = object->getPosition();
        if (position)
        {
            JsonValue location = makeObject();
            location.objectValue["x"] = makeNumber(static_cast<double>(position->m_x));
            location.objectValue["y"] = makeNumber(static_cast<double>(position->m_y));
            location.objectValue["z"] = makeNumber(static_cast<double>(position->m_z));
            result.objectValue["position"] = location;
        }

        Player *controller = object->getControllingPlayer();
        if (controller)
            result.objectValue["player_id"] = makeNumber(static_cast<double>(controller->getPlayerIndex()));

        Team *team = object->getTeam();
        if (team)
            result.objectValue["team_name"] = makeString(team->getName().getCString());

        BodyModuleInterface *body = object->getBodyModule();
        if (body)
        {
            result.objectValue["health"] = makeNumber(static_cast<double>(body->getHealth()));
            result.objectValue["max_health"] = makeNumber(static_cast<double>(body->getMaxHealth()));
        }

        return result;
    }

    static JsonValue buildPlayerJson(const Player *player)
    {
        JsonValue result = makeObject();
        result.objectValue["player_id"] = makeNumber(static_cast<double>(player->getPlayerIndex()));
        result.objectValue["side"] = makeString(player->getSide().getCString());
        result.objectValue["name_key"] = makeNumber(static_cast<double>(player->getPlayerNameKey()));
        result.objectValue["money"] = makeNumber(static_cast<double>(player->getMoney()->countMoney()));
        return result;
    }

    static bool getNumberMember(const JsonValue &object, const char *key, double &out)
    {
        const JsonValue *value = object.findMember(key);
        if (!value || !value->isNumber())
            return false;
        out = value->numberValue;
        return true;
    }

    static bool getIntMember(const JsonValue &object, const char *key, int &out)
    {
        const JsonValue *value = object.findMember(key);
        if (!value)
            return false;
        return value->getInt(out);
    }

    static bool getBoolMember(const JsonValue &object, const char *key, bool &out)
    {
        const JsonValue *value = object.findMember(key);
        if (!value || !value->isBoolean())
            return false;
        out = value->booleanValue;
        return true;
    }

    static bool getStringMember(const JsonValue &object, const char *key, std::string &out)
    {
        const JsonValue *value = object.findMember(key);
        if (!value || !value->isString())
            return false;
        out = value->stringValue;
        return true;
    }

    static std::string makeErrorResponse(const std::string &message)
    {
        JsonValue payload = makeObject();
        payload.objectValue["status"] = makeString("error");
        payload.objectValue["message"] = makeString(message);
        return serializeJson(payload);
    }

    static std::string makeOkResponse()
    {
        JsonValue payload = makeObject();
        payload.objectValue["status"] = makeString("ok");
        return serializeJson(payload);
    }

    static GameMessage *buildGameMessageFromJson(const JsonValue &request, std::string &error)
    {
        const JsonValue *typeValue = request.findMember("message_type");
        if (!typeValue)
            typeValue = request.findMember("type");
        if (!typeValue || !typeValue->isNumber())
        {
            error = "Missing or invalid message_type";
            return nullptr;
        }

        int messageType = 0;
        if (!typeValue->getInt(messageType))
        {
            error = "message_type must be an integer";
            return nullptr;
        }

        GameMessage *message = newInstance(GameMessage)(static_cast<GameMessage::Type>(messageType));
        if (!message)
        {
            error = "Failed to allocate GameMessage";
            return nullptr;
        }

        const JsonValue *args = request.findMember("arguments");
        if (!args)
            args = request.findMember("args");

        if (args)
        {
            if (!args->isArray())
            {
                deleteInstance(message);
                error = "arguments must be an array";
                return nullptr;
            }

            for (size_t index = 0; index < args->arrayValue.size(); ++index)
            {
                const JsonValue &argument = args->arrayValue[index];
                if (!argument.isObject())
                {
                    deleteInstance(message);
                    error = "Each argument must be an object";
                    return nullptr;
                }

                std::string argumentType;
                if (!getStringMember(argument, "type", argumentType))
                {
                    deleteInstance(message);
                    error = "Argument missing type field";
                    return nullptr;
                }

                for (size_t i = 0; i < argumentType.size(); ++i)
                    argumentType[i] = static_cast<char>(tolower(argumentType[i]));

                if (argumentType == "integer" || argumentType == "int")
                {
                    int value;
                    if (!getIntMember(argument, "value", value))
                    {
                        deleteInstance(message);
                        error = "Integer argument missing value";
                        return nullptr;
                    }
                    message->appendIntegerArgument(value);
                }
                else if (argumentType == "real" || argumentType == "float" || argumentType == "double")
                {
                    double value;
                    if (!getNumberMember(argument, "value", value))
                    {
                        deleteInstance(message);
                        error = "Real argument missing value";
                        return nullptr;
                    }
                    message->appendRealArgument(static_cast<Real>(value));
                }
                else if (argumentType == "boolean" || argumentType == "bool")
                {
                    bool value;
                    if (!getBoolMember(argument, "value", value))
                    {
                        deleteInstance(message);
                        error = "Boolean argument missing value";
                        return nullptr;
                    }
                    message->appendBooleanArgument(value ? TRUE : FALSE);
                }
                else if (argumentType == "location" || argumentType == "coord")
                {
                    double x, y, z;
                    if (getNumberMember(argument, "x", x) && getNumberMember(argument, "y", y))
                    {
                        if (!getNumberMember(argument, "z", z))
                            z = 0.0;
                    }
                    else
                    {
                        const JsonValue *locationValue = argument.findMember("value");
                        if (!locationValue || !locationValue->isObject() ||
                            !getNumberMember(*locationValue, "x", x) ||
                            !getNumberMember(*locationValue, "y", y))
                        {
                            deleteInstance(message);
                            error = "Location argument requires x and y";
                            return nullptr;
                        }
                        if (!getNumberMember(*locationValue, "z", z))
                            z = 0.0;
                    }
                    Coord3D coord;
                    coord.m_x = static_cast<Real>(x);
                    coord.m_y = static_cast<Real>(y);
                    coord.m_z = static_cast<Real>(z);
                    message->appendLocationArgument(coord);
                }
                else
                {
                    deleteInstance(message);
                    error = "Unsupported argument type: " + argumentType;
                    return nullptr;
                }
            }
        }

        return message;
    }

    static JsonValue buildStateJson()
    {
        JsonValue state = makeObject();
        state.objectValue["status"] = makeString("ok");
        state.objectValue["frame"] = makeNumber(static_cast<double>(TheGameLogic->getFrame()));
        state.objectValue["map_width"] = makeNumber(static_cast<double>(TheGameLogic->getWidth()));
        state.objectValue["map_height"] = makeNumber(static_cast<double>(TheGameLogic->getHeight()));

        PlayerList *playerList = ThePlayerList;
        if (playerList)
        {
            JsonValue players = makeArray();
            for (Int i = 0; i < playerList->getPlayerCount(); ++i)
            {
                Player *player = playerList->getNthPlayer(i);
                if (player)
                    players.arrayValue.push_back(buildPlayerJson(player));
            }
            state.objectValue["players"] = players;
        }

        JsonValue objects = makeArray();
        Object *object = TheGameLogic->getFirstObject();
        while (object)
        {
            objects.arrayValue.push_back(buildObjectJson(object));
            object = object->getNextObject();
        }
        state.objectValue["objects"] = objects;
        state.objectValue["object_count"] = makeNumber(static_cast<double>(objects.arrayValue.size()));

        return state;
    }

    static JsonValue buildPlayersJson()
    {
        JsonValue wrapper = makeObject();
        wrapper.objectValue["status"] = makeString("ok");
        JsonValue players = makeArray();
        PlayerList *playerList = ThePlayerList;
        if (playerList)
        {
            for (Int i = 0; i < playerList->getPlayerCount(); ++i)
            {
                Player *player = playerList->getNthPlayer(i);
                if (player)
                    players.arrayValue.push_back(buildPlayerJson(player));
            }
        }
        wrapper.objectValue["players"] = players;
        wrapper.objectValue["player_count"] = makeNumber(static_cast<double>(players.arrayValue.size()));
        return wrapper;
    }

    static JsonValue buildObjectsJson()
    {
        JsonValue wrapper = makeObject();
        wrapper.objectValue["status"] = makeString("ok");
        JsonValue objects = makeArray();
        Object *object = TheGameLogic->getFirstObject();
        while (object)
        {
            objects.arrayValue.push_back(buildObjectJson(object));
            object = object->getNextObject();
        }
        wrapper.objectValue["objects"] = objects;
        wrapper.objectValue["object_count"] = makeNumber(static_cast<double>(objects.arrayValue.size()));
        return wrapper;
    }

    static JsonValue buildActionResponse(const std::string &action)
    {
        JsonValue wrapper = makeObject();
        wrapper.objectValue["status"] = makeString("ok");
        wrapper.objectValue["action"] = makeString(action);
        return wrapper;
    }

    static bool buildRequestResponse(const JsonValue &request, std::string &response)
    {
        const JsonValue *actionValue = request.findMember("action");
        if (!actionValue || !actionValue->isString())
        {
            response = makeErrorResponse("Missing or invalid action field");
            return false;
        }

        std::string action = actionValue->stringValue;
        for (size_t i = 0; i < action.size(); ++i)
            action[i] = static_cast<char>(tolower(action[i]));

        if (action == "ping")
        {
            response = serializeJson(buildActionResponse("ping"));
            return true;
        }
        if (action == "get_state")
        {
            response = serializeJson(buildStateJson());
            return true;
        }
        if (action == "list_players")
        {
            response = serializeJson(buildPlayersJson());
            return true;
        }
        if (action == "list_objects")
        {
            response = serializeJson(buildObjectsJson());
            return true;
        }
        if (action == "create_game_message")
        {
            std::string error;
            GameMessage *message = buildGameMessageFromJson(request, error);
            if (!message)
            {
                response = makeErrorResponse(error);
                return false;
            }

            if (!TheCommandList)
            {
                deleteInstance(message);
                response = makeErrorResponse("TheCommandList is not initialized");
                return false;
            }

            TheCommandList->appendMessage(message);
            response = serializeJson(makeActionResponse("create_game_message"));
            return true;
        }

        response = makeErrorResponse("Unknown action: " + action);
        return false;
    }

    struct PendingRequest
    {
        SOCKET clientSocket;
        JsonValue request;
    };

    struct PendingResponse
    {
        SOCKET clientSocket;
        std::string payload;
    };

    struct ClientState
    {
        std::string receiveBuffer;
    };

    class RpcImplementation
    {
    public:
        explicit RpcImplementation(unsigned short port)
            : m_port(port)
            , m_listenSocket(INVALID_SOCKET)
            , m_stopRequested(false)
            , m_initialized(false)
        {
            m_initialized = initialize();
        }

        ~RpcImplementation()
        {
            stop();
        }

        bool isInitialized() const
        {
            return m_initialized;
        }

        void processRequests()
        {
            std::deque<PendingRequest> pending;
            {
                std::lock_guard<std::mutex> lock(m_requestMutex);
                pending.swap(m_requestQueue);
            }

            for (size_t i = 0; i < pending.size(); ++i)
            {
                std::string response;
                buildRequestResponse(pending[i].request, response);
                queueResponse(pending[i].clientSocket, response);
            }
        }

    private:
        unsigned short m_port;
        SOCKET m_listenSocket;
        std::atomic<bool> m_stopRequested;
        bool m_initialized;
        std::thread m_worker;
        std::mutex m_clientMutex;
        std::map<SOCKET, ClientState> m_clients;
        std::mutex m_requestMutex;
        std::deque<PendingRequest> m_requestQueue;
        std::mutex m_responseMutex;
        std::deque<PendingResponse> m_responseQueue;

        bool initialize()
        {
            printf("[RPC] Server initialized on port %d\n", m_port);
            WSADATA wsaData;
            if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0)
                return false;

            m_listenSocket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
            if (m_listenSocket == INVALID_SOCKET)
            {
                WSACleanup();
                return false;
            }

            u_long nonBlocking = 1;
            ioctlsocket(m_listenSocket, FIONBIO, &nonBlocking);

            sockaddr_in address;
            memset(&address, 0, sizeof(address));
            address.sin_family = AF_INET;
            address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            address.sin_port = htons(m_port);

            int reuse = 1;
            setsockopt(m_listenSocket, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char *>(&reuse), sizeof(reuse));

            if (bind(m_listenSocket, reinterpret_cast<sockaddr *>(&address), sizeof(address)) == SOCKET_ERROR)
            {
                closesocket(m_listenSocket);
                m_listenSocket = INVALID_SOCKET;
                WSACleanup();
                return false;
            }

            if (listen(m_listenSocket, SOMAXCONN) == SOCKET_ERROR)
            {
                closesocket(m_listenSocket);
                m_listenSocket = INVALID_SOCKET;
                WSACleanup();
                return false;
            }

            m_worker = std::thread(&RpcImplementation::run, this);
            return true;
        }

        void stop()
        {
            m_stopRequested = true;
            if (m_worker.joinable())
                m_worker.join();

            closeAllClients();
            if (m_listenSocket != INVALID_SOCKET)
            {
                closesocket(m_listenSocket);
                m_listenSocket = INVALID_SOCKET;
            }
            WSACleanup();
        }

        void closeAllClients()
        {
            std::lock_guard<std::mutex> lock(m_clientMutex);
            for (std::map<SOCKET, ClientState>::iterator it = m_clients.begin(); it != m_clients.end(); ++it)
            {
                closesocket(it->first);
            }
            m_clients.clear();
        }

        void queueResponse(SOCKET clientSocket, const std::string &payload)
        {
            std::lock_guard<std::mutex> lock(m_responseMutex);
            PendingResponse entry = { clientSocket, payload + "\n" };
            m_responseQueue.push_back(entry);
        }

        void queueRequest(SOCKET clientSocket, JsonValue &&request)
        {
            std::lock_guard<std::mutex> lock(m_requestMutex);
            PendingRequest entry = { clientSocket, std::move(request) };
            m_requestQueue.push_back(entry);
        }

        void run()
        {
            while (!m_stopRequested)
            {
                printf("[RPC] Worker thread started\n");
                fd_set readSet;
                FD_ZERO(&readSet);
                if (m_listenSocket != INVALID_SOCKET)
                    FD_SET(m_listenSocket, &readSet);

                SOCKET maxSocket = m_listenSocket;
                {
                    std::lock_guard<std::mutex> lock(m_clientMutex);
                    for (std::map<SOCKET, ClientState>::const_iterator it = m_clients.begin(); it != m_clients.end(); ++it)
                    {
                        FD_SET(it->first, &readSet);
                        if (it->first > maxSocket)
                            maxSocket = it->first;
                    }
                }

                timeval timeout;
                timeout.tv_sec = 0;
                timeout.tv_usec = 100000;

                int result = select(static_cast<int>(maxSocket + 1), &readSet, nullptr, nullptr, &timeout);
                if (result == SOCKET_ERROR)
                {
                    Sleep(10);
                    continue;
                }

                if (m_listenSocket != INVALID_SOCKET && FD_ISSET(m_listenSocket, &readSet))
                {
                    sockaddr_in clientAddress;
                    int clientAddressSize = sizeof(clientAddress);
                    SOCKET clientSocket = accept(m_listenSocket, reinterpret_cast<sockaddr *>(&clientAddress), &clientAddressSize);
                    printf("[RPC] Client connected\n");
                    if (clientSocket != INVALID_SOCKET)
                    {
                        u_long nonBlocking = 1;
                        ioctlsocket(clientSocket, FIONBIO, &nonBlocking);
                        std::lock_guard<std::mutex> lock(m_clientMutex);
                        m_clients[clientSocket] = ClientState();
                    }
                }

                std::vector<SOCKET> clientSockets;
                {
                    std::lock_guard<std::mutex> lock(m_clientMutex);
                    for (std::map<SOCKET, ClientState>::const_iterator it = m_clients.begin(); it != m_clients.end(); ++it)
                        clientSockets.push_back(it->first);
                }

                for (size_t index = 0; index < clientSockets.size(); ++index)
                {
                    SOCKET clientSocket = clientSockets[index];
                    if (!FD_ISSET(clientSocket, &readSet))
                        continue;

                    char buffer[4096];
                    int bytesRead = recv(clientSocket, buffer, static_cast<int>(sizeof(buffer)), 0);
                    if (bytesRead <= 0)
                    {
                        closeClient(clientSocket);
                        continue;
                    }

                    std::string incoming(buffer, bytesRead);
                    bool removeClient = false;
                    {
                        std::lock_guard<std::mutex> lock(m_clientMutex);
                        std::map<SOCKET, ClientState>::iterator stateIt = m_clients.find(clientSocket);
                        if (stateIt == m_clients.end())
                            continue;
                        ClientState &state = stateIt->second;
                        state.receiveBuffer += incoming;

                        while (!state.receiveBuffer.empty())
                        {
                            size_t newlinePos = state.receiveBuffer.find('\n');
                            if (newlinePos == std::string::npos)
                                break;

                            std::string line = state.receiveBuffer.substr(0, newlinePos);
                            if (!line.empty() && line.back() == '\r')
                                line.pop_back();
                            state.receiveBuffer.erase(0, newlinePos + 1);

                            if (line.empty())
                                continue;

                            JsonValue request;
                            std::string error;
                            if (parseJson(line, request, error))
                            {
                                queueRequest(clientSocket, std::move(request));
                            }
                            else
                            {
                                queueResponse(clientSocket, makeErrorResponse(error));
                            }
                        }
                    }

                    if (removeClient)
                        closeClient(clientSocket);
                }

                flushResponses();
            }

            flushResponses();
        }

        void closeClient(SOCKET clientSocket)
        {
            std::lock_guard<std::mutex> lock(m_clientMutex);
            std::map<SOCKET, ClientState>::iterator it = m_clients.find(clientSocket);
            if (it != m_clients.end())
            {
                closesocket(it->first);
                m_clients.erase(it);
            }
        }

        void flushResponses()
        {
            std::deque<PendingResponse> pending;
            {
                std::lock_guard<std::mutex> lock(m_responseMutex);
                pending.swap(m_responseQueue);
            }

            for (size_t i = 0; i < pending.size(); ++i)
            {
                const PendingResponse &entry = pending[i];
                int totalSent = 0;
                int messageSize = static_cast<int>(entry.payload.size());

                while (totalSent < messageSize)
                {
                    int bytesSent = send(entry.clientSocket, entry.payload.c_str() + totalSent, messageSize - totalSent, 0);
                    if (bytesSent == SOCKET_ERROR)
                    {
                        closeClient(entry.clientSocket);
                        break;
                    }
                    totalSent += bytesSent;
                }
            }
        }
    };
}

JsonTcpRpcServer *gRpcServer = nullptr;

JsonTcpRpcServer::JsonTcpRpcServer(unsigned short port)
    : m_impl(nullptr)
{
    m_impl = new RpcImplementation(port);
    if (!m_impl->isInitialized())
    {
        delete m_impl;
        m_impl = nullptr;
    }
}

JsonTcpRpcServer::~JsonTcpRpcServer()
{
    delete m_impl;
    m_impl = nullptr;
}

void JsonTcpRpcServer::ProcessRequests()
{
    if (m_impl)
        m_impl->processRequests();
}
