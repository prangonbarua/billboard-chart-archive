#!/bin/bash

# Setup Automatic Billboard Data Updates
# This script configures your system to automatically update chart data

echo "============================================================"
echo "🤖 Billboard Auto-Update Setup"
echo "============================================================"
echo ""

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "📁 Project directory: $SCRIPT_DIR"
echo ""

# Check for billboard.py
echo "Checking dependencies..."
if python3 -c "import billboard" 2>/dev/null; then
    echo "✓ billboard.py installed"
else
    echo "⚠️  billboard.py not found"
    echo ""
    read -p "Install billboard.py now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pip3 install billboard.py
        echo "✓ billboard.py installed"
    else
        echo "⚠️  Warning: Billboard direct updates will not work without billboard.py"
    fi
fi

echo ""
echo "============================================================"
echo "Choose Auto-Update Method:"
echo "============================================================"
echo ""
echo "1. On Server Startup (Railway/Heroku)"
echo "   ✓ Already configured in app.py"
echo "   ✓ Updates every time server restarts"
echo "   ✓ No additional setup needed"
echo ""
echo "2. Weekly Cron Job (macOS/Linux)"
echo "   ✓ Runs automatically every Wednesday at 9 AM"
echo "   ✓ Updates in background"
echo "   ✓ Requires cron setup"
echo ""
echo "3. Manual Updates Only"
echo "   ✓ Run 'python3 smart_update.py' when needed"
echo "   ✓ Full control over updates"
echo ""

read -p "Select option (1/2/3): " option

case $option in
    1)
        echo ""
        echo "✅ Server Startup Updates"
        echo "============================================================"
        echo "Already configured! Your website will automatically check for"
        echo "updates every time it starts. No additional setup needed."
        echo ""
        echo "How it works:"
        echo "  1. Server starts → smart_update.py runs"
        echo "  2. Tries Kaggle update (fast)"
        echo "  3. Falls back to Billboard direct if needed"
        echo "  4. Server loads with latest data"
        ;;

    2)
        echo ""
        echo "📅 Setting up Weekly Cron Job"
        echo "============================================================"

        # Create cron entry
        CRON_ENTRY="0 9 * * 3 cd $SCRIPT_DIR && python3 smart_update.py >> $SCRIPT_DIR/update.log 2>&1"

        echo "This will add the following cron job:"
        echo ""
        echo "$CRON_ENTRY"
        echo ""
        echo "Schedule: Every Wednesday at 9:00 AM"
        echo "Log file: $SCRIPT_DIR/update.log"
        echo ""

        read -p "Add this cron job? (y/n) " -n 1 -r
        echo ""

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Backup existing crontab
            crontab -l > /tmp/crontab_backup 2>/dev/null

            # Check if entry already exists
            if crontab -l 2>/dev/null | grep -q "smart_update.py"; then
                echo "⚠️  Cron job already exists. Replacing..."
                crontab -l 2>/dev/null | grep -v "smart_update.py" | crontab -
            fi

            # Add new cron entry
            (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

            echo "✅ Cron job added!"
            echo ""
            echo "To verify:"
            echo "  crontab -l"
            echo ""
            echo "To view logs:"
            echo "  tail -f $SCRIPT_DIR/update.log"
            echo ""
            echo "To remove:"
            echo "  crontab -e"
        else
            echo "❌ Cancelled. To add manually:"
            echo "  crontab -e"
            echo ""
            echo "Then add this line:"
            echo "$CRON_ENTRY"
        fi
        ;;

    3)
        echo ""
        echo "📝 Manual Updates"
        echo "============================================================"
        echo "Run updates whenever you want with:"
        echo ""
        echo "  cd $SCRIPT_DIR"
        echo "  python3 smart_update.py"
        echo ""
        echo "For force update:"
        echo "  python3 smart_update.py --force"
        ;;

    *)
        echo ""
        echo "Invalid option. Exiting."
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "Test the Updater"
echo "============================================================"
echo ""
read -p "Run a test update now? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    cd "$SCRIPT_DIR"
    python3 smart_update.py
fi

echo ""
echo "============================================================"
echo "✅ Setup Complete!"
echo "============================================================"
echo ""
echo "Your website will now automatically update chart data!"
echo ""
echo "Useful commands:"
echo "  python3 smart_update.py          - Run update now"
echo "  python3 smart_update.py --force  - Force update"
echo "  crontab -l                       - View cron jobs"
echo "  tail -f update.log               - Watch update logs"
echo ""
