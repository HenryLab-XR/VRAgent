# Door Key Gate Refactor

Date: 2026-05-14

## Summary

- Refactored `DoorController` from `startLocked/isLocked` state to `requiresKey + requiredKeyObject + unlockedByKey`.
- Added `CanOpen()` and `TryUnlockWith(GameObject insertedObject)`.
- `Open()` now respects key requirements; `Close()` is always allowed.
- Kept `Unlock()` only as a compatibility/debug path.
- Pantry and kitchen socket receivers now validate the inserted object before advancing recipe state.

## Door Configuration

- `Door_A_Lobby`: `requiresKey=false`
- `Door_Pantry`: `requiresKey=true`, `requiredKeyObject=Key_Pantry`
- `Door_Kitchen`: `requiresKey=true`, `requiredKeyObject=Badge_Kitchen`
- `Door_FinalExit`: `requiresKey=true`, unlocked by the existing delivery flow through `ServingCounterSocket.finalExitDoor`

## Checks

- Confirmed `DoorController` no longer serializes `startLocked` or stores an `isLocked` field.
- Confirmed Pantry and Kitchen receivers no longer call `DoorController.Unlock()` directly.
- Confirmed `TryUnlockWith()` accepts the configured key object or a child transform of that object.
- Confirmed DoorNode XRTriggerable bindings no longer call `Unlock()` and now route through `Open()`.
- Confirmed `Door_Pantry` binds PantryKeyUnlockReceiver to its DoorController and `Door_Kitchen` binds KitchenBadgeUnlockReceiver to its DoorController.
- Confirmed `RecipeController.SetPowerEnabled()` checks `doorPantryUnlocked` instead of `hasPantryKey`.
- Confirmed stale persistent socket UnityEvents that directly called recipe door-unlock setters were removed from `Kitchen_TestRoom.unity` and `DoorNode.prefab`.
- Updated the gold manual test plan so pantry/kitchen socket actions pass `inserted_object_fileID` and door triggers only call `Open()`.
- Validated the gold manual test plan parses as JSON.
