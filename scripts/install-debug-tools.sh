#!/bin/bash
# Auto-install dap debugger if not present
if ! command -v dap &> /dev/null; then
    echo "Installing dap debugger..."
    curl -fsSL https://raw.githubusercontent.com/AlmogBaku/debug-skill/master/install.sh | bash
fi
