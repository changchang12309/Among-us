# 🚀 Space Werewolf - Among Us Simplified Version

> A turn-based strategy deduction game inspired by Among Us, built with Python Tkinter.
> Supporting 4-10 players for local multiplayer.

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Tkinter](https://img.shields.io/badge/GUI-Tkinter-green.svg)](https://docs.python.org/3/library/tkinter.html)
[![License](https://img.shields.io/badge/License-LGPL--2.1-yellow.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/Version-v1.2.0-orange.svg)]()

---

## 🎮 Game Introduction

**Space Werewolf (太空狼人杀)** is a turn-based strategy deduction game inspired by the classic game Among Us. Players are assigned to two roles: **Crewmate** or **Impostor**, engaging in a tense and thrilling battle of survival and deception aboard a spaceship.

Created by three Chinese middle school students. We have very limited time, please stay tuned for future updates.

---

## 📋 Game Rules

### Role Assignment

| Player Count | Impostor Count |
|:------------:|:--------------:|
| 4-6 players  | 1 Impostor     |
| 7-10 players | 2 Impostors    |

### Victory Conditions

**🏆 Crewmate Victory:**
- Complete all regular tasks (each crewmate needs to complete 3 tasks)
- Vote out all impostors

**💀 Impostor Victory:**
- Impostor count equals crewmate count
- Crew fails to repair within 2 rounds after oxygen system is sabotaged

---

## 🖥️ Game Interface

### Main Menu
- Player count selection (4-10 players)
- Start Game button

### Role Viewing
- Display player name and role (Crewmate/Impostor)
- Role-specific tips
- Task count display (crewmates only)

### Main Game Interface
- **Top Status Bar**: Global round number, action steps, emergency meeting count, cooldown status
- **Left Map**: Spaceship map, click to move
- **Right Info Panel**: Current player info, task progress
- **Bottom Log**: Game event records

---

## ✨ Core Features

### 🚶 Movement System
- 4 action steps per round
- Click rooms on the map to move
- Can only move to adjacent rooms

### 📋 Task System (Crewmates)
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

### 💣 Bomb System (Impostors) - Added in v1.1.0

**Place Bomb:**
- Impostors can place bombs in any room
- Consumes 1 action step
- Placement cooldown: 5 rounds
- Bomb countdown: 3 minutes (independent real-time timing)

**Bomb Explosion Effects:**
- Kills all crewmates in the room where bomb explodes (impostors unaffected)
- Explodes in Oxygen → Triggers oxygen repair task (2-round countdown)
- Explodes in Security → Triggers security camera repair task
- Explodes in Spaceship Hall → Disables emergency meeting for 2 rounds

**Defuse Bomb Task:**
- Crewmates can defuse bombs when in a room with a bomb
- Cut 4 wires in correct order
- 30-second countdown, explosion on wrong cut or timeout

### 🏚️ Ruin Cleaning System - Added in v1.2.0

**Ruin Generation:**
- Bomb explosions cause the room to become ruined
- Ruined rooms cannot execute normal tasks
- 🏚️ marker displayed on map

**Clean Ruins:**
- Crewmates must click "Clean Ruins" button in ruined rooms
- Drag debris into trash can to complete cleaning
- Room functions restored after cleaning
- Cannot initiate emergency meeting when Spaceship Hall is ruined

### ⚠️ Sabotage System (Impostors)
Impostors can sabotage the following systems:

**Oxygen System:**
- After sabotage, crewmates receive temporary repair task
- Crew has 2 rounds to repair, failure means impostor victory

**Security Cameras:**
- After sabotage, requires task completion to restore
- After viewing cameras, all players enter 2-round cooldown

**Sabotage Cooldown:** - Added in v1.2.0
- Sabotage system has 2-round cooldown
- Cannot sabotage again during cooldown

### 📹 Security Cameras Room
- Only available in Security
- Shows player and body counts for all rooms
- Rooms with bombs marked with red bold border
- **Complete View**: Sets 2-round cooldown for all alive players
- **Report Body**: Can directly report bodies to trigger discussion

### 🗣️ Emergency Meeting
- Each player has 2 chances to initiate
- Only available in **Spaceship Hall**
- Initiating enters discussion and voting phase
- Disabled for 2 rounds when Spaceship Hall is ruined or bomb explodes

### 🗳️ Voting System
- All alive players vote in turn
- Player with most votes is exiled
- Tie means no one is exiled

### 👻 Spectator Mode
- Players enter spectator mode after death
- Can switch perspective to view any room
- Body positions fixed and displayed

---

## ⏱️ Cooldown Mechanism

| Skill | Cooldown | Description |
|:------:|:--------:|:------------|
| Kill | 3 rounds | Impostor kills crewmate |
| Shuttle | 3 rounds | Impostor teleports to any room |
| Monitor | 2 rounds | Effective for all players after viewing monitor |
| Bomb | 5 rounds | Impostor places bomb |
| Sabotage | 2 rounds | Impostor sabotages systems |
| Round 1 | Disabled | Impostors prohibited from killing and shuttling |

---

## 🗺️ Spaceship Map

```
                    Upper Engine
                         |
  Lower Engine -- Medbay -- Reactor
       |                        |
  Electrical -- Fuel -- Spaceship Hall -- Oxygen
                     |    |           |
                  Admin   |        Security
                            |           |
                         Communications -- Security
```

---

## 📁 Project Structure

```
Among-us/
├── main_gui.py      # Main interface logic, GUI core
├── game.py          # Game logic class
├── player.py        # Player class definition
├── roles.py         # Role class definition (Crewmate/Impostor)
├── map.py           # Game map definition
├── tasks.py         # Task system definition
├── haikediannao.py  # Backup task interface
├── build/           # Build directory (PyInstaller)
├── dist/            # Distribution output directory (packaged exe)
├── README.md        # Project documentation
└── LICENSE          # LGPL-2.1 License
```

---

## 🛠️ Tech Stack

- **Language**: Python 3.11
- **GUI Framework**: Tkinter
- **Packaging Tool**: PyInstaller

---

## 🚀 How to Run

### Development Mode
```bash
python main_gui.py
```

### Packaged Execution
The project is packaged with PyInstaller and can run directly:
```bash
# Windows
dist/太空狼人杀v1.2.0/太空狼人杀v1.2.0.exe
```

---

## 🎯 Game Flow

1. **Select Player Count** (4-10 players)
2. **View Role Info** (Each player views in turn)
3. **Game Starts**:
   - Turn-based actions (move, complete tasks, kill, etc.)
   - Can initiate emergency meetings
   - Discussion and voting phases
4. **Game Ends**: Victory side and final identity reveal

---

## 📝 Development Notes

This game was developed by three Chinese middle school students during their spare time, with design inspiration from Among Us. The game has been simplified and innovated based on the original version, adding various special features such as security cameras, shuttle function, bomb system, and ruin cleaning.

### Main Features
- ✅ Complete graphical task interfaces
- ✅ Deep blue tech-style UI design
- ✅ Multiple cooldown and restriction mechanisms
- ✅ Spectator mode
- ✅ Body report and voting systems
- ✅ Oxygen emergency sabotage mechanism
- ✅ Bomb system and defuse tasks
- ✅ Ruin cleaning system

---

## 📜 Version History

| Version | Update Content |
|:--------:|:--------------|
| v1.0.0 | Initial version, basic game features |
| v1.1.0 | Bomb system, defuse task, security camera bomb markers |
| v1.1.7 | Download data task optimization, fan click detection optimization |
| v1.2.0 | Ruin cleaning system, sabotage cooldown, interface optimization |

---

## 📄 License

This project is licensed under the GNU Lesser General Public License v2.1 - see the [LICENSE](./LICENSE) file for details.

---

<div align="center">
Made with ❤️ by three middle school students
</div>
