#!/usr/bin/env python3
"""Dump the Accessibility tree of a Cursor window level by level."""

import subprocess
import sys
import tempfile
import os


def run_osascript(script: str, timeout: float = 30.0) -> str:
    fd, path = tempfile.mkstemp(suffix=".applescript")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        result = subprocess.run(
            ["osascript", path],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "osascript failed")
        return result.stdout.strip()
    finally:
        os.unlink(path)


def list_children_at_path(pid: int, window_index: int, path_indices: list[int]) -> str:
    """Get info about children at a specific path in the AX tree.
    
    path_indices is a list of 1-based child indices from the window root.
    E.g. [1, 2] means: window -> child 1 -> child 2 -> list its children
    """
    nav = f"set target to window {window_index} of targetProc\n"
    for idx in path_indices:
        nav += f"    set target to UI element {idx} of target\n"
    
    script = f"""
on joinLines(itemsList)
    if (count of itemsList) is 0 then return ""
    set oldTID to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set joinedText to itemsList as text
    set AppleScript's text item delimiters to oldTID
    return joinedText
end joinLines

tell application "System Events"
    set targetProc to first application process whose unix id is {pid}
    {nav}
    set outputLines to {{}}
    
    -- Info about target itself
    set tRole to ""
    try
        set tRole to (role of target as text)
    end try
    set tName to ""
    try
        set tName to (get name of target) as text
        if tName is "missing value" then set tName to ""
    end try
    set tSub to ""
    try
        set tSub to (subrole of target as text)
        if tSub is "missing value" then set tSub to ""
    end try
    set tDesc to ""
    try
        set tDesc to (description of target as text)
        if tDesc is "missing value" then set tDesc to ""
    end try
    set tRoleDesc to ""
    try
        set tRoleDesc to (role description of target as text)
        if tRoleDesc is "missing value" then set tRoleDesc to ""
    end try
    set tChildCount to 0
    try
        set tChildCount to (count of UI elements of target)
    end try
    set end of outputLines to "SELF" & tab & tRole & tab & tSub & tab & tName & tab & tDesc & tab & tRoleDesc & tab & (tChildCount as text)
    
    -- List children
    set childIdx to 0
    repeat with childElem in UI elements of target
        set childIdx to childIdx + 1
        set cRole to ""
        try
            set cRole to (role of childElem as text)
        end try
        set cName to ""
        try
            set cName to (get name of childElem) as text
            if cName is "missing value" then set cName to ""
        end try
        set cSub to ""
        try
            set cSub to (subrole of childElem as text)
            if cSub is "missing value" then set cSub to ""
        end try
        set cDesc to ""
        try
            set cDesc to (description of childElem as text)
            if cDesc is "missing value" then set cDesc to ""
        end try
        set cRoleDesc to ""
        try
            set cRoleDesc to (role description of childElem as text)
            if cRoleDesc is "missing value" then set cRoleDesc to ""
        end try
        set cChildCount to 0
        try
            set cChildCount to (count of UI elements of childElem)
        end try
        set end of outputLines to (childIdx as text) & tab & cRole & tab & cSub & tab & cName & tab & cDesc & tab & cRoleDesc & tab & (cChildCount as text)
    end repeat
    return my joinLines(outputLines)
end tell
"""
    return run_osascript(script, timeout=30.0)


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 36173
    window_index = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    
    path_str = sys.argv[3] if len(sys.argv) > 3 else ""
    if path_str:
        path_indices = [int(x) for x in path_str.split(".")]
    else:
        path_indices = []

    path_display = ".".join(str(x) for x in path_indices) if path_indices else "(window root)"
    print(f"PID={pid} Window={window_index} Path={path_display}")
    print(f"Columns: index | role | subrole | name | description | roleDescription | childCount")
    print("---")
    try:
        output = list_children_at_path(pid, window_index, path_indices)
        print(output)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
