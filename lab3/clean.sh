#!/usr/bin/env bash

OUT_DIR="out"

# Check if the directory actually exists
if [ ! -d "$OUT_DIR" ]; then
    echo "[INFO] The '$OUT_DIR/' directory does not exist. Nothing to clean."
    exit 0
fi

count=0

# Enable nullglob so the loop doesn't execute if the directory is empty
shopt -s nullglob

# Iterate through everything inside the 'out' directory
for item in "$OUT_DIR"/*; do
    # Check if it's a regular file (not a subdirectory)
    if [ -f "$item" ]; then
        # Attempt to remove the file
        if rm -f "$item"; then
            echo "[-] Deleted: $(basename "$item")"
            ((count++))
        else
            echo "[!] Error deleting $(basename "$item")"
        fi
    fi
done

echo ""
echo "[*] Cleanup complete. $count files removed from '$OUT_DIR/'."