tell application "System Events"
    tell process "NotificationCenter"
        try
            set wins to windows
            if (count of wins) is 0 then
                return "no_notification"
            end if
            perform action "AXPress" of first group of scroll area 1 of group 1 of group 1 of window 1
            return "pressed"
        on error
            return "no_notification"
        end try
    end tell
end tell
