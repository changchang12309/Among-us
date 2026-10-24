# Space Werewolf - Among Us Simplified Version

A Space Werewolf tabletop game developed with Python Tkinter, supporting single-device play (4-10 players) and LAN multiplayer (2-10 players).

## Game Introduction

**Space Werewolf** is a turn-based strategy deduction game inspired by the classic game Among Us. Players are assigned to two roles: **Crewmate** or **Impostor**, engaging in a tense and thrilling battle of survival and deception aboard a spaceship.

Created by three Chinese middle school students. We have very limited time, please stay tuned for future updates.

## Game Rules

### Role Assignment

| Player Count | Impostor Count |
|:------------:|:--------------:|
| 4-6 players  | 1 Impostor     |
| 7-10 players | 2 Impostors    |

### Victory Conditions

**Crewmate Victory:**
- Complete all regular tasks (each crewmate needs to complete 3 tasks)
- Vote out all impostors

**Impostor Victory:**
- Impostor count equals crewmate count (with at least one player eliminated)
- Crew fails to repair within the time limit after oxygen system is sabotaged

## Game Interface

### Mode Selection Lobby (Added in v2.0.0)
- **Single Player**: the original same-screen turn-based mode
- **Create Room**: shows the local LAN IP and waits for other players
- **Join Room**: enter the host's IP and your own name to connect

### Role Viewing
- Display player name and role (Crewmate/Impostor)
- Role-specific tips
- Task count display (crewmates only)

### Main Game Interface
- **Top Status Bar**: Global round number, action steps, emergency meeting count, cooldown status
- **Left Map**: Spaceship map, click to move
- **Right Info Panel**: Current player info, task progress
- **Bottom Log**: Game event records

## Core Features

### Movement System
- 4 action steps per round
- Click rooms on the map to move
- Can only move to adjacent rooms

### Task System (Crewmates)
Crewmates need to complete 3 regular tasks:

| Task Name | Location | Difficulty |
|:----------:|:--------:|:----------:|
| Fix Wires | Electrical | ★ |
| Clean Filter | Oxygen | ★ |
| Body Scan | Medbay | ★★ |
| Download Data | Communications | ★★ |
| Calibrate Engines | Engine | ★★ |
| Repair Reactor | Reactor | ★★★ |
| Fuel Engines | Fuel | ★★ |
| Start Satellite | Security | ★★★ |
| Submit Code | Admin | ★★★ |

### Bomb System (Impostors) - Added in v1.1.0

**Place Bomb:**
- Impostors can place bombs in any room
- Consumes 1 action step
- Placement cooldown: 5 rounds (150 seconds in multiplayer)
- Bomb countdown: 3 minutes in single player (independent real-time timing); 60 seconds in multiplayer

**Bomb Explosion Effects:**
- Kills all crewmates in the room where bomb explodes (impostors unaffected)
- Explodes in Oxygen → Triggers oxygen repair task
- Explodes in Security → Triggers security camera repair task
- Explodes in Spaceship Hall → Disables emergency meeting for 2 rounds

**Defuse Bomb Task:**
- Crewmates can defuse bombs when in a room with a bomb
- Cut 4 wires in correct order
- 30-second countdown, explosion on wrong cut or timeout

### Ruin Cleaning System - Added in v1.2.0

**Ruin Generation:**
- Bomb explosions cause the room to become ruined
- Ruined rooms cannot execute normal tasks
- 🏚️ marker displayed on map

**Clean Ruins:**
- Crewmates must click "Clean Ruins" button in ruined rooms
- Drag debris into trash can to complete cleaning
- Room functions restored after cleaning
- Cannot initiate emergency meeting when Spaceship Hall is ruined

### Sabotage System (Impostors)
Impostors can sabotage the following systems:

**Oxygen System:**
- After sabotage, crewmates receive temporary repair task
- Crew must repair within the time limit, failure means impostor victory

**Security Cameras:**
- After sabotage, requires task completion to restore
- After viewing cameras, all players enter cooldown

**Sabotage Cooldown:** - Added in v1.2.0
- 2-round cooldown in single player, 90 seconds in multiplayer
- Cannot sabotage again during cooldown

### Security Cameras Room
- Only available in Security
- Shows player and body counts for all rooms
- Rooms with bombs marked with red bold border
- **Complete View**: Sets cooldown for all alive players
- **Report Body**: Can directly report bodies to trigger discussion

### Emergency Meeting
- Each player has 2 chances to initiate
- Only available in **Spaceship Hall**
- Initiating enters discussion and voting phase
- Disabled for 2 rounds when Spaceship Hall is ruined or bomb explodes

### Voting System
- All alive players vote in turn
- Player with most votes is exiled
- Tie means no one is exiled

### Spectator Mode
- Players enter spectator mode after death
- Can switch perspective to view any room
- Body positions fixed and displayed

### LAN Multiplayer - Added in v2.0.0

**Room System:**
- The host listens on port `8888`; clients join by entering the host's IP
- Custom player names supported; duplicates are auto-renamed (e.g. `Player2(1)`)
- Player count and player list are shown in real time

**Role Assignment:**
- Assigned randomly by the host and distributed to every client
- Each client only sees its own role to avoid identity leaks

**Position Synchronization:**
- The host runs a `12346` sync server inside the game process
- Full room state (positions, alive status, task progress, sabotage, bombs, bodies) is broadcast every 500ms
- Position updates are relayed to other players but never echoed back to the sender

**Detached Processes:**
- Game windows are independent of the lobby; closing the lobby does not affect the game
- Each client writes its own log: `game_host_*.log`, `game_client_*.log`
- Exceptions and crashes are recorded in `crash_<pid>.log`

**Multiplayer Cooldowns:**
- Single player keeps round-based cooldowns; multiplayer uses second-based real-time cooldowns
- See the "Cooldown Mechanism" table below

## Cooldown Mechanism

| Skill | Single (rounds) | Multiplayer (seconds) | Description |
|:-----:|:---------------:|:---------------------:|:------------|
| Kill | 3 | 45 | Impostor kills crewmate |
| Shuttle | 3 | 60 | Impostor teleports to any room |
| Monitor | 2 | 45 | Effective for all players after viewing monitor |
| Bomb | 5 | 150 | Impostor places bomb |
| Sabotage | 2 | 90 | Impostor sabotages systems |
| Bomb fuse | 180s | 60s | Time from placement to explosion |
| Round 1 | Disabled | Disabled | Impostors prohibited from killing and shuttling |

## Spaceship Map

```
                    Upper Engine
                         |
  Lower Engine -- Medbay -- Reactor
       |                        |
  Electrical -- Fuel -- Spaceship Hall -- Oxygen
                   |  |                  |
                 Admin |              Security
                       |                  |
                Communications -------------
```

## Project Structure

```
Among-us-main-basic-tkinter-/
├── multiplayer.py   # v2.0.0 entry: mode lobby, room server, role assignment
├── main_gui.py      # Main game interface, position sync, graphical tasks
├── game.py          # Game logic class
├── player.py        # Player class definition
├── roles.py         # Role class definition (Crewmate/Impostor)
├── map.py           # Game map definition
├── tasks.py         # Task system definition (13 graphical tasks)
├── room_state.py    # Multiplayer room state container
├── crewmate_entry.py / impostor_entry.py  # Role entry scripts
├── haikediannao.py  # Morse code mini-game
├── tests/           # Headless multiplayer protocol self-test
├── build/           # Build directory
└── dist/            # Distribution output directory
```

## Tech Stack

- **Language**: Python 3.11
- **GUI Framework**: Tkinter
- **Networking**: TCP socket + JSON line-delimited protocol (ports 8888 / 12346)
- **Packaging Tool**: PyInstaller

## How to Run

### Development Mode
```bash
python multiplayer.py
```
Choose from the mode selection screen: Single Player / Create Room / Join Room.

### LAN Multiplayer
1. The host selects "Create Room" and notes the LAN IP shown
2. Other players select "Join Room", enter that IP and their name
3. Once enough players have joined, the host clicks "Start Game"

> Note: both ends must be on the same LAN, with TCP ports `8888` and `12346` allowed.

### Packaged Execution
A PyInstaller-packaged exe will be provided with the release.

## Game Flow

**Single Player:**
1. Select player count (4-10 players)
2. View role info (each player views in turn)
3. Turn-based actions (move, complete tasks, kill, etc.)
4. Game ends: victory side and final identity reveal

**Multiplayer:**
1. Create/join a room and wait for players
2. The host starts; each client opens its own game window
3. Real-time actions with position synchronization
4. Game ends: results synced across all clients

## Development Notes

This game was developed by three Chinese middle school students during their spare time, with design inspiration from Among Us. The game has been simplified and innovated based on the original version, adding various special features such as security cameras, shuttle function, bomb system, and ruin cleaning.

### Main Features
- Complete graphical task interfaces
- Deep blue tech-style UI design
- Multiple cooldown and restriction mechanisms
- Spectator mode
- Body report and voting systems
- Oxygen emergency sabotage mechanism
- Bomb system and defuse tasks
- Ruin cleaning system
- LAN multiplayer with real-time position sync (v2.0.0)

## Version History

| Version | Update Content |
|:--------:|:--------------|
| v1.0.0 | Initial version, basic game features |
| v1.1.0 | Bomb system, defuse task, security camera bomb markers |
| v1.1.7 | Download data task optimization, fan click detection optimization |
| v1.2.0 | Ruin cleaning system, sabotage cooldown, interface optimization |
| v2.0.0 | LAN multiplayer, position sync, detached processes, multiplayer cooldown balance, multiple crash fixes |
