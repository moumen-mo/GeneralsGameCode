import os

filepath = "GeneralsMD/Code/GameEngine/Source/Common/RTS/Player.cpp"

replacements = {
    "UnsignedShort prototypeCount = m_playerTeamPrototypes.size();": 
    "UnsignedShort prototypeCount = static_cast<UnsignedShort>(m_playerTeamPrototypes.size());",
    "UnsignedShort scienceCount = m_sciences.size();": 
    "UnsignedShort scienceCount = static_cast<UnsignedShort>(m_sciences.size());",
    "UnsignedShort percentProductionChangeCount = m_kindOfPercentProductionChangeList.size();": 
    "UnsignedShort percentProductionChangeCount = static_cast<UnsignedShort>(m_kindOfPercentProductionChangeList.size());",
    "UnsignedShort timerListSize = m_specialPowerReadyTimerList.size();": 
    "UnsignedShort timerListSize = static_cast<UnsignedShort>(m_specialPowerReadyTimerList.size());",
}

if os.path.exists(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    for old, new in replacements.items():
        content = content.replace(old, new)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully updated Player.cpp")
else:
    print(f"File not found: {filepath}")