# GameMessage Types and Command Creation Reference

## Overview
The game uses a message-passing system to handle all player input and game commands:
1. **Raw Input** → Mouse/keyboard events captured
2. **MessageStream** → Events processed by translators
3. **CommandList** → Validated commands queued for execution
4. **GameLogic** → Commands executed in game update

---

## GameMessage::Type Enum

### Location
[MessageStream.h](GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h#L105)

### Categories

#### System Messages
- `MSG_INVALID` - Invalid message (should never occur)
- `MSG_FRAME_TICK` - Sent once per frame
- `MSG_CLEAR_GAME_DATA` - Clear all game data
- `MSG_NEW_GAME` - Start new game

#### Raw Mouse Input (MSG_RAW_MOUSE_BEGIN to MSG_RAW_MOUSE_END)
- `MSG_RAW_MOUSE_POSITION` - Cursor position
- `MSG_RAW_MOUSE_LEFT_BUTTON_DOWN/UP` - Left button events
- `MSG_RAW_MOUSE_LEFT_CLICK` / `MSG_RAW_MOUSE_LEFT_DOUBLE_CLICK`
- `MSG_RAW_MOUSE_LEFT_DRAG` - Mouse drag with button held
- `MSG_RAW_MOUSE_MIDDLE_*` - Middle button variants
- `MSG_RAW_MOUSE_RIGHT_*` - Right button variants
- `MSG_RAW_MOUSE_WHEEL` - Mouse wheel scroll

#### Refined Mouse Messages (Recommended for UI processing)
- `MSG_MOUSE_LEFT_CLICK` - (pixelRegion, modifiers)
- `MSG_MOUSE_LEFT_DOUBLE_CLICK`
- `MSG_MOUSE_MIDDLE_CLICK` / `MSG_MOUSE_RIGHT_CLICK`
- `MSG_MOUSE_MIDDLE_DOUBLE_CLICK` / `MSG_MOUSE_RIGHT_DOUBLE_CLICK`

#### Raw Keyboard Input
- `MSG_RAW_KEY_DOWN` - (KeyDefType)
- `MSG_RAW_KEY_UP` - (KeyDefType)

#### Meta Messages (Client-side only, NOT sent over network)
**Selection & Team Management:**
- `MSG_META_SELECT_TEAM0-9` - Select user-defined team
- `MSG_META_ADD_TEAM0-9` - Add team to selection
- `MSG_META_CREATE_TEAM0-9` - Create team from selected
- `MSG_META_VIEW_TEAM0-9` - Center view on team
- `MSG_META_SELECT_ALL` - Select all units
- `MSG_META_SELECT_ALL_AIRCRAFT` - Select all aircraft
- `MSG_META_SELECT_MATCHING_UNITS` - Select matching unit types
- `MSG_META_SELECT_NEXT_UNIT` / `MSG_META_SELECT_PREV_UNIT`
- `MSG_META_SELECT_NEXT_WORKER` / `MSG_META_SELECT_PREV_WORKER`
- `MSG_META_SELECT_NEXT_IDLE_WORKER` - ⭐ Added feature
- `MSG_META_SELECT_HERO` - Select hero unit
- `MSG_META_VIEW_COMMAND_CENTER` - Center on command center

**Unit Commands:**
- `MSG_META_SCATTER` - Selected units scatter
- `MSG_META_STOP` - Selected units stop
- `MSG_META_DEPLOY` - Selected units deploy
- `MSG_META_CREATE_FORMATION` - Create formation
- `MSG_META_FOLLOW` - Follow command
- `MSG_META_ATTACK_MOVE` - Attack-move mode

**Camera Control:**
- `MSG_META_SAVE_VIEW1-8` - Save camera view
- `MSG_META_VIEW_VIEW1-8` - Load camera view
- `MSG_META_BEGIN_CAMERA_ROTATE_LEFT/RIGHT` - Rotate camera
- `MSG_META_ALT_CAMERA_ROTATE_LEFT/RIGHT` - 45° increments ⭐
- `MSG_META_BEGIN_CAMERA_ZOOM_IN/OUT` - Zoom camera
- `MSG_META_CAMERA_RESET` - Reset camera
- `MSG_META_TOGGLE_CAMERA_TRACKING_DRAWABLE` - Track unit

**UI & Gameplay:**
- `MSG_META_CHAT_PLAYERS` - Chat to all
- `MSG_META_CHAT_ALLIES` - Chat to allies
- `MSG_META_DIPLOMACY` - Diplomacy screen
- `MSG_META_OPTIONS` - Options screen
- `MSG_META_TAKE_SCREENSHOT`
- `MSG_META_TOGGLE_PAUSE` - Pause game ⭐
- `MSG_META_TOGGLE_PAUSE_ALT` - Alternative pause key ⭐
- `MSG_META_STEP_FRAME` - Step one frame ⭐
- `MSG_META_TOGGLE_CONTROL_BAR` - Show/hide control bar

---

#### Command Hints (For GUI Validation - Do NOT send over network)
- `MSG_DO_MOVETO_HINT` - Move command valid
- `MSG_DO_ATTACK_OBJECT_HINT` - Attack valid
- `MSG_DO_FORCE_ATTACK_GROUND_HINT` - Force attack ground valid
- `MSG_DO_FORCE_ATTACK_OBJECT_HINT` - Force attack object valid
- `MSG_GET_REPAIRED_HINT` - Repair valid
- `MSG_GET_HEALED_HINT` - Heal valid
- `MSG_DO_REPAIR_HINT` - Unit can repair
- `MSG_RESUME_CONSTRUCTION_HINT` - Resume construction valid
- `MSG_ENTER_HINT` - Can enter
- `MSG_DOCK_HINT` - Can dock
- `MSG_ADD_WAYPOINT_HINT` - Can add waypoint
- `MSG_SET_RALLY_POINT_HINT` - Can set rally point
- `MSG_HIJACK_HINT` - Can hijack
- `MSG_SABOTAGE_HINT` - Can sabotage
- `MSG_SNIPE_VEHICLE_HINT` - Can snipe
- `MSG_DEFECTOR_HINT` - Can convert defector
- `MSG_DO_SALVAGE_HINT` - Can salvage

---

#### Network Command Messages (MSG_BEGIN_NETWORK_MESSAGES = 1000 to MSG_END_NETWORK_MESSAGES = 1999)

**Selection Commands:**
- `MSG_CREATE_SELECTED_GROUP` - (Bool createNewGroup, objectID1, objectID2, ...)
- `MSG_CREATE_SELECTED_GROUP_NO_SOUND` - Same but without sound
- `MSG_DESTROY_SELECTED_GROUP` - (teamID)
- `MSG_REMOVE_FROM_SELECTED_GROUP` - (objectID1, objectID2, ...)
- `MSG_SELECTED_GROUP_COMMAND` - (teamID) Next command applies to team

**Hotkey Teams (MSG_CREATE_TEAM0-9, MSG_SELECT_TEAM0-9, MSG_ADD_TEAM0-9)**
- `MSG_CREATE_TEAM0-9` - Create hotkey squad from selection
- `MSG_SELECT_TEAM0-9` - Set hotkey squad as selection
- `MSG_ADD_TEAM0-9` - Add hotkey squad to selection

**Movement Commands:**
- `MSG_DO_MOVETO` - Move to location (location)
- `MSG_DO_ATTACKMOVETO` - Attack-move to location (location)
- `MSG_DO_FORCEMOVETO` - Force move to location (location)
- `MSG_ADD_WAYPOINT` - Add waypoint (location)
- `MSG_DO_GUARD_POSITION` - Guard position (location)
- `MSG_DO_GUARD_OBJECT` - Guard object (objectID)
- `MSG_DO_STOP` - Stop all movement
- `MSG_DO_SCATTER` - Scatter formation

**Combat Commands:**
- `MSG_DO_ATTACK_OBJECT` - Attack target (objectID)
- `MSG_DO_FORCE_ATTACK_OBJECT` - Force attack (objectID)
- `MSG_DO_FORCE_ATTACK_GROUND` - Force attack ground (location)
- `MSG_DO_ATTACKSQUAD` - Attack squad (numObjects, objectID1, ...)
- `MSG_SWITCH_WEAPONS` - Switch weapon slot

**Special Actions:**
- `MSG_DO_WEAPON` - Fire specific weapon
- `MSG_DO_WEAPON_AT_LOCATION` - Fire weapon at location
- `MSG_DO_WEAPON_AT_OBJECT` - Fire weapon at object
- `MSG_DO_SPECIAL_POWER` - Execute special power
- `MSG_DO_SPECIAL_POWER_AT_LOCATION` - Special power at location
- `MSG_DO_SPECIAL_POWER_AT_OBJECT` - Special power at object
- `MSG_DO_SPECIAL_POWER_OVERRIDE_DESTINATION` - Override special power destination
- `MSG_DO_SALVAGE` - Salvage object
- `MSG_INTERNET_HACK` - Internet hack
- `MSG_DO_CHEER` - Play cheer animation

**Unit Interactions:**
- `MSG_ENTER` - Enter object (objectID)
- `MSG_DOCK` - Dock with object (objectID)
- `MSG_EXIT` - Exit from contained object
- `MSG_EVACUATE` - Dump out contained objects
- `MSG_COMBATDROP_AT_LOCATION` - Combat drop rappellers at location
- `MSG_COMBATDROP_AT_OBJECT` - Combat drop at object
- `MSG_EXECUTE_RAILED_TRANSPORT` - Execute railed transport

**Repair & Heal:**
- `MSG_DO_REPAIR` - Dozer repairs target (objectID)
- `MSG_GET_REPAIRED` - Unit gets repaired at clicked object (objectID)
- `MSG_GET_HEALED` - Unit gets healed at clicked object (objectID)
- `MSG_RESUME_CONSTRUCTION` - Resume construction on building

**Building Commands:**
- `MSG_DOZER_CONSTRUCT` - Start building construction (objectID) 
- `MSG_DOZER_CONSTRUCT_LINE` - Start line construction (for walls)
- `MSG_DOZER_CANCEL_CONSTRUCT` - Cancel construction
- `MSG_SELL` - Sell structure (objectID)
- `MSG_TOGGLE_OVERCHARGE` - Toggle power plant overcharge
- `MSG_SET_RALLY_POINT` - Set rally point (objectID, location)

**Production Commands:**
- `MSG_PURCHASE_SCIENCE` - Purchase a science/upgrade
- `MSG_QUEUE_UPGRADE` - Queue upgrade research
- `MSG_CANCEL_UPGRADE` - Cancel upgrade
- `MSG_QUEUE_UNIT_CREATE` - Queue unit production
- `MSG_CANCEL_UNIT_CREATE` - Cancel unit production

**Hacking/Special Commands:**
- `MSG_CONVERT_TO_CARBOMB` - Convert vehicle to car bomb
- `MSG_CAPTUREBUILDING` - Capture building
- `MSG_DISABLEVEHICLE_HACK` - Hack disable vehicle
- `MSG_STEALCASH_HACK` - Steal cash hack
- `MSG_DISABLEBUILDING_HACK` - Disable building hack
- `MSG_SNIPE_VEHICLE` - Snipe vehicle
- `MSG_SELF_DESTRUCT` - Self destruct units

**UI/Replay/Network:**
- `MSG_AREA_SELECTION` - (pixelRegion) Rectangular selection
- `MSG_CREATE_FORMATION` - Create formation
- `MSG_LOGIC_CRC` - CRC from logic (multiplayer sync)
- `MSG_SET_REPLAY_CAMERA` - Track camera position for replays
- `MSG_CLEAR_INGAME_POPUP_MESSAGE` - Clear popup
- `MSG_PLACE_BEACON` - Place beacon at location
- `MSG_REMOVE_BEACON` - Remove beacon
- `MSG_SET_BEACON_TEXT` - Set beacon text
- `MSG_SET_MINE_CLEARING_DETAIL` - Mine clearing detail
- `MSG_ENABLE_RETALIATION_MODE` - Toggle retaliation mode

---

## CommandList and Message Processing Flow

### Architecture
```
┌─────────────────────────────────────────────┐
│ Raw Input (Mouse, Keyboard)                 │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ TheMessageStream                            │
│ - Receives raw input messages               │
│ - Passes through translator chain           │
│ - Valid commands moved to CommandList       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ TheCommandList                              │
│ - Queue of validated game commands          │
│ - Processed by GameLogic::processCommandList│
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ GameLogic::logicMessageDispatcher           │
│ - Executes each command on game state       │
│ - Updates unit AI, positions, etc.          │
└─────────────────────────────────────────────┘
```

### Key Classes

**MessageStream** [MessageStream.h](GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h#L763)
```cpp
class MessageStream : public GameMessageList {
  void propagateMessages();  // Send through translators
  TranslatorID attachTranslator(GameMessageTranslator *t, Priority);
  GameMessage *appendMessage(GameMessage::Type type);
  GameMessage *insertMessage(GameMessage::Type type, GameMessage *after);
};
```

**CommandList** [MessageStream.h](GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h#L805)
```cpp
class CommandList : public GameMessageList {
  void init();                           // Initialize
  void reset();                          // Clear all messages
  void appendMessageList(GameMessage *list);  // Add messages
};
```

**GameMessage** [MessageStream.h](GeneralsMD/Code/GameEngine/Include/Common/MessageStream.h#L95)
```cpp
class GameMessage : public MemoryPoolObject {
  Type getType() const;
  UnsignedByte getArgumentCount() const;
  const GameMessageArgumentType *getArgument(Int index) const;
  
  // Append arguments
  void appendIntegerArgument(Int arg);
  void appendRealArgument(Real arg);
  void appendBooleanArgument(Bool arg);
  void appendObjectIDArgument(ObjectID arg);
  void appendLocationArgument(const Coord3D& arg);
  void appendPixelArgument(const ICoord2D& arg);
  void appendTeamIDArgument(UnsignedInt arg);
  // ... more appendX methods
};
```

### Message Processing
[GameLogic.cpp](GeneralsMD/Code/GameEngine/Source/GameLogic/System/GameLogic.cpp#L2615)
```cpp
void GameLogic::processCommandList(CommandList *list) {
  GameMessage* msg;
  for(msg = list->getFirstMessage(); msg; msg = msg->next()) {
    logicMessageDispatcher(msg, nullptr);
  }
  // CRC validation for multiplayer sync...
}
```

[GameLogicDispatch.cpp](GeneralsMD/Code/GameEngine/Source/GameLogic/System/GameLogicDispatch.cpp#L346)
```cpp
void GameLogic::logicMessageDispatcher(GameMessage *msg, void *userData) {
  Player *msgPlayer = ThePlayerList->getNthPlayer(msg->getPlayerIndex());
  
  // Create AIGroup from currently selected objects
  AIGroupPtr currentlySelectedGroup = TheAI->createGroup();
  msgPlayer->getCurrentSelectionAsAIGroup(currentlySelectedGroup);
  
  // Dispatch based on message type
  switch(msg->getType()) {
    case GameMessage::MSG_DO_MOVETO:
    case GameMessage::MSG_DO_ATTACK_OBJECT:
    case GameMessage::MSG_DO_REPAIR:
    // ... etc
  }
}
```

---

## Command Creation Examples

### 1. Unit Selection Command
**Location:** [SelectionXlat.cpp](GeneralsMD/Code/GameEngine/Source/GameClient/MessageStream/SelectionXlat.cpp#L247)
```cpp
// Create a selection message with multiple units
GameMessage *msg = TheMessageStream->appendMessage(
  GameMessage::MSG_CREATE_SELECTED_GROUP_NO_SOUND
);

// First argument: whether to create new selection (vs add to existing)
msg->appendBooleanArgument(createNewGroup);

// Add object IDs for each selected unit
msg->appendObjectIDArgument(objectID1);
msg->appendObjectIDArgument(objectID2);
msg->appendObjectIDArgument(objectID3);
```

**Logic Handler** [GameLogicDispatch.cpp](GeneralsMD/Code/GameEngine/Source/GameLogic/System/GameLogicDispatch.cpp#L1670)
```cpp
case GameMessage::MSG_CREATE_SELECTED_GROUP:
{
  Bool createNewGroup = msg->getArgument(0)->boolean;
  Bool firstObject = TRUE;
  
  for (Int i = 1; i < msg->getArgumentCount(); ++i) {
    Object *obj = findObjectByID(msg->getArgument(i)->objectID);
    if (!obj) continue;
    
    selectObject(obj, createNewGroup && firstObject, msgPlayer->getPlayerMask());
    firstObject = FALSE;
  }
  break;
}
```

---

### 2. Move Command
**Location:** [CommandXlat.cpp](GeneralsMD/Code/GameEngine/Source/GameClient/MessageStream/CommandXlat.cpp#L1006)
```cpp
GameMessage::Type CommandTranslator::issueMoveToLocationCommand(
  const Coord3D *pos,
  Drawable *drawableInWay,
  CommandEvaluateType commandType)
{
  GameMessage::Type msgType = GameMessage::MSG_INVALID;
  
  // Determine which movement command to use
  if (TheInGameUI->isInWaypointMode())
    msgType = GameMessage::MSG_ADD_WAYPOINT;
  else if (TheInGameUI->isInAttackMoveToMode())
    msgType = GameMessage::MSG_DO_ATTACKMOVETO;
  else if (TheInGameUI->isInForceMoveToMode())
    msgType = GameMessage::MSG_DO_FORCEMOVETO;
  else
    msgType = GameMessage::MSG_DO_MOVETO;
  
  // Only create message if actually issuing command (not just testing)
  if (commandType == DO_COMMAND) {
    GameMessage *moveMsg = TheMessageStream->appendMessage(msgType);
    moveMsg->appendLocationArgument(*pos);  // Target destination
  }
  
  // Play unit voice response
  pickAndPlayUnitVoiceResponse(
    TheInGameUI->getAllSelectedDrawables(),
    GameMessage::MSG_DO_MOVETO
  );
  
  return msgType;
}
```

**Logic Handler** [GameLogicDispatch.cpp](GeneralsMD/Code/GameEngine/Source/GameLogic/System/GameLogicDispatch.cpp#L897)
```cpp
case GameMessage::MSG_DO_MOVETO:
{
  if (currentlySelectedGroup) {
    Coord3D location = msg->getArgument(0)->location;
    currentlySelectedGroup->groupMoveTo(&location, NO_MAX_SHOTS_LIMIT, CMD_FROM_PLAYER);
  }
  break;
}
```

---

### 3. Attack Command
**Location:** [CommandXlat.cpp](GeneralsMD/Code/GameEngine/Source/GameClient/MessageStream/CommandXlat.cpp#L1068)
```cpp
GameMessage::Type CommandTranslator::createAttackMessage(
  Drawable *draw,
  Drawable *other,
  CommandEvaluateType commandType)
{
  GameMessage::Type msgType = GameMessage::MSG_INVALID;
  
  // Validate both attacker and target exist and have objects
  if (!draw->getObject() || !other->getObject())
    return msgType;
  
  msgType = GameMessage::MSG_DO_ATTACK_OBJECT;
  
  // Only create message if really issuing command
  if (commandType == DO_COMMAND) {
    GameMessage *attackMsg = TheMessageStream->appendMessage(msgType);
    
    // Pass the TARGET'S object ID
    attackMsg->appendObjectIDArgument(other->getObject()->getID());
  }
  
  return msgType;
}
```

**Wrapper Function** [CommandXlat.cpp](GeneralsMD/Code/GameEngine/Source/GameClient/MessageStream/CommandXlat.cpp#L1115)
```cpp
GameMessage::Type CommandTranslator::issueAttackCommand(
  Drawable *target,
  CommandEvaluateType commandType,
  GUICommandType command)
{
  if (!target || !target->getObject())
    return GameMessage::MSG_INVALID;
  
  // Determine attack type based on GUI command
  GameMessage::Type msgType = GameMessage::MSG_DO_ATTACK_OBJECT;
  
  if (commandType == DO_COMMAND) {
    GameMessage *attackMsg = TheMessageStream->appendMessage(msgType);
    attackMsg->appendObjectIDArgument(target->getObject()->getID());
    
    if (TheStatsCollector)
      TheStatsCollector->incrementAttackCount();
  }
  
  return msgType;
}
```

**Logic Handler** [GameLogicDispatch.cpp](GeneralsMD/Code/GameEngine/Source/GameLogic/System/GameLogicDispatch.cpp#L1323)
```cpp
case GameMessage::MSG_DO_ATTACK_OBJECT:
{
  Object *enemy = findObjectByID(msg->getArgument(0)->objectID);
  
  if (enemy && currentlySelectedGroup) {
    currentlySelectedGroup->releaseWeaponLockForGroup(LOCKED_TEMPORARILY);
    currentlySelectedGroup->groupAttackObject(
      enemy,
      NO_MAX_SHOTS_LIMIT,
      CMD_FROM_PLAYER
    );
  }
  break;
}
```

---

### 4. Special Power Command
**Location:** [CommandXlat.h](GeneralsMD/Code/GameEngine/Include/GameClient/CommandXlat.h#L64)
```cpp
GameMessage::Type issueSpecialPowerCommand(
  const CommandButton *command,
  CommandEvaluateType commandType,
  Drawable *target,
  const Coord3D *pos,
  Object* ignoreSelObj);
```

Example usage: Creates `MSG_DO_SPECIAL_POWER_AT_LOCATION` or `MSG_DO_SPECIAL_POWER_AT_OBJECT`

---

## Global Pointers for Command Access

```cpp
extern MessageStream *TheMessageStream;  // Input message stream
extern CommandList *TheCommandList;      // Command queue
extern GameLogic *TheGameLogic;          // Game state
extern PlayerList *ThePlayerList;        // Players
```

---

## Message Argument Types

```cpp
union GameMessageArgumentType {
  Int integer;              // Integer values
  Real real;                // Floating point
  Bool boolean;             // True/false
  ObjectID objectID;        // Game object reference
  DrawableID drawableID;    // Drawable entity reference
  UnsignedInt teamID;       // Team/squad ID
  Coord3D location;         // 3D world position
  ICoord2D pixel;           // 2D screen pixel
  IRegion2D pixelRegion;    // 2D screen region
  UnsignedInt timestamp;    // Frame timestamp
  WideChar wChar;           // Unicode character
};

enum GameMessageArgumentDataType {
  ARGUMENTDATATYPE_INTEGER,
  ARGUMENTDATATYPE_REAL,
  ARGUMENTDATATYPE_BOOLEAN,
  ARGUMENTDATATYPE_OBJECTID,
  ARGUMENTDATATYPE_DRAWABLEID,
  ARGUMENTDATATYPE_TEAMID,
  ARGUMENTDATATYPE_LOCATION,
  ARGUMENTDATATYPE_PIXEL,
  ARGUMENTDATATYPE_PIXELREGION,
  ARGUMENTDATATYPE_TIMESTAMP,
  ARGUMENTDATATYPE_WIDECHAR,
  ARGUMENTDATATYPE_UNKNOWN
};
```

---

## Key Translators

All translators inherit from `GameMessageTranslator`:

1. **CommandTranslator** [CommandXlat.h](GeneralsMD/Code/GameEngine/Include/GameClient/CommandXlat.h#L35)
   - Converts raw input → tactical commands
   - Methods: `createMoveToLocationMessage()`, `createAttackMessage()`, etc.

2. **GUICommandTranslator** [GUICommandTranslator.h](GeneralsMD/Code/GameEngine/Include/GameClient/GUICommandTranslator.h#L39)
   - Handles control bar button clicks

3. **SelectionTranslator** (SelectionXlat.cpp)
   - Handles unit selection via mouse/keyboard

4. **HintSpy** (HintSpy.cpp)
   - Provides UI hints without sending network commands

---

## Notes

- **Network Sync:** All commands between MSG_BEGIN_NETWORK_MESSAGES (1000) and MSG_END_NETWORK_MESSAGES (1999) are network-synchronized
- **Meta Messages:** Messages between MSG_BEGIN_META_MESSAGES and MSG_END_META_MESSAGES are client-only (never sent over network)
- **Command Types:** Each message can be `DO_COMMAND` (real command) or `TEST_COMMAND` (just validation for UI hints)
- **CRC Validation:** Game logic validates CRCs each frame for multiplayer consistency
- **AI Groups:** Selected units are grouped into an `AIGroup` for issuing commands atomically
