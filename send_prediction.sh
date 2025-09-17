#!/bin/bash

# Script to send prediction API call with contents of context-out.txt
# Runs every 15 minutes via cron

OUTPUT_FILE="/root/context-out.txt"
ENDPOINT="https://daisyplus-staging.up.railway.app/api/v1/prediction/23c2e709-29a4-45d6-be6a-71e5a6a986e5"

# Check if context-out.txt exists
if [ ! -f "$OUTPUT_FILE" ]; then
    echo "$(date): Warning - $OUTPUT_FILE does not exist" >> /var/log/prediction_cron.log
    exit 1
fi

# Extract only the Output section and trim whitespace
QUESTION_CONTENT=$(awk '/^Output:/{flag=1; next} flag' "$OUTPUT_FILE" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed '/^$/d')

# Escape quotes and special characters for JSON
ESCAPED_CONTENT=$(echo "$QUESTION_CONTENT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed 's/$/\\n/' | tr -d '\n' | sed 's/\\n$//')

# Make the API call and capture response
RESPONSE=$(curl -s "$ENDPOINT" \
     -X POST \
     -d "{\"question\": \"$ESCAPED_CONTENT\"}" \
     -H "Content-Type: application/json")

# Log the response
echo "$RESPONSE" >> /var/log/prediction_cron.log
echo "$(date): Prediction API call completed" >> /var/log/prediction_cron.log

# Check if response contains <prompt></prompt> tags
if echo "$RESPONSE" | grep -q "<prompt>.*</prompt>"; then
    # Extract content between <prompt> and </prompt> tags
    PROMPT_CONTENT=$(echo "$RESPONSE" | sed -n 's/.*<prompt>\(.*\)<\/prompt>.*/\1/p')

    if [ ! -z "$PROMPT_CONTENT" ]; then
        # Wrap prompt with template
        WRAPPED_PROMPT="You are a senior software developer operating a linux machine with full permissions you are working on a development task with the current active request: $PROMPT_CONTENT"

        # Escape quotes and special characters for JSON
        ESCAPED_PROMPT=$(echo "$WRAPPED_PROMPT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g')

        # Try port 8000 first, then 8088 as fallback
        EXECUTE_RESPONSE=""

        # Check if this is a file creation command and use direct execution
        if echo "$PROMPT_CONTENT" | grep -q "create.*file"; then
            # Try port 8000
            EXECUTE_RESPONSE=$(curl -s --connect-timeout 5 -X 'POST' \
                'http://localhost:8000/api/execute' \
                -H 'accept: application/json' \
                -H 'Content-Type: application/json' \
                -d "{\"term\": \"claude -p \\\"$ESCAPED_PROMPT\\\"\"}" 2>/dev/null)

            # If 8000 fails, try 8088
            if [ -z "$EXECUTE_RESPONSE" ] || echo "$EXECUTE_RESPONSE" | grep -q "error\|failed"; then
                EXECUTE_RESPONSE=$(curl -s --connect-timeout 5 -X 'POST' \
                    'http://localhost:8088/api/execute' \
                    -H 'accept: application/json' \
                    -H 'Content-Type: application/json' \
                    -d "{\"term\": \"claude -p \\\"$ESCAPED_PROMPT\\\"\"}" 2>/dev/null)
            fi
        else
            # Try port 8000
            EXECUTE_RESPONSE=$(curl -s --connect-timeout 5 -X 'POST' \
                'http://localhost:8000/api/execute' \
                -H 'accept: application/json' \
                -H 'Content-Type: application/json' \
                -d "{\"command\": \"claude -p \\\"$ESCAPED_PROMPT\\\"\"}" 2>/dev/null)

            # If 8000 fails, try 8088
            if [ -z "$EXECUTE_RESPONSE" ] || echo "$EXECUTE_RESPONSE" | grep -q "error\|failed"; then
                EXECUTE_RESPONSE=$(curl -s --connect-timeout 5 -X 'POST' \
                    'http://localhost:8088/api/execute' \
                    -H 'accept: application/json' \
                    -H 'Content-Type: application/json' \
                    -d "{\"command\": \"claude -p \\\"$ESCAPED_PROMPT\\\"\"}" 2>/dev/null)
            fi
        fi

        # Log the execute API call
        echo "$(date): Found prompt tags, executing command: $PROMPT_CONTENT" >> /var/log/prediction_cron.log
        echo "Execute API response: $EXECUTE_RESPONSE" >> /var/log/prediction_cron.log

        # Extract timestamp from initial response for follow-up
        INITIAL_TIMESTAMP=$(echo "$RESPONSE" | grep -o '"timestamp":"[^"]*"' | head -1 | cut -d'"' -f4)
        if [ -z "$INITIAL_TIMESTAMP" ]; then
            INITIAL_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")
        fi

        # Prepare follow-up response with results
        FOLLOWUP_PROMPT="Aight boss heres my response to your request from $INITIAL_TIMESTAMP: $EXECUTE_RESPONSE"
        ESCAPED_FOLLOWUP=$(echo "$FOLLOWUP_PROMPT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed 's/$/\\n/' | tr -d '\n' | sed 's/\\n$//')

        # Send follow-up response to daisy API
        FOLLOWUP_RESPONSE=$(curl -s "$ENDPOINT" \
            -X POST \
            -d "{\"question\": \"$ESCAPED_FOLLOWUP\"}" \
            -H "Content-Type: application/json")

        # Log the follow-up call
        echo "$(date): Follow-up response sent to daisy API" >> /var/log/prediction_cron.log
        echo "Follow-up API response: $FOLLOWUP_RESPONSE" >> /var/log/prediction_cron.log

        # Check if follow-up response contains prompt tags and execute
        if echo "$FOLLOWUP_RESPONSE" | grep -q "<prompt>.*</prompt>"; then
            # Extract content between <prompt> and </prompt> tags from follow-up
            FOLLOWUP_PROMPT_CONTENT=$(echo "$FOLLOWUP_RESPONSE" | sed -n 's/.*<prompt>\(.*\)<\/prompt>.*/\1/p')

            if [ ! -z "$FOLLOWUP_PROMPT_CONTENT" ]; then
                # Wrap follow-up prompt with template
                WRAPPED_FOLLOWUP_PROMPT="You are a senior software developer operating a linux machine with full permissions you are working on a development task with the current active request: $FOLLOWUP_PROMPT_CONTENT"

                # Escape quotes and special characters for JSON
                ESCAPED_FOLLOWUP_PROMPT=$(echo "$WRAPPED_FOLLOWUP_PROMPT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g')

                # Execute follow-up command in Claude (try port 8000 first, then 8088)
                FOLLOWUP_EXECUTE_RESPONSE=""

                # Try port 8000
                FOLLOWUP_EXECUTE_RESPONSE=$(curl -s --connect-timeout 5 -X 'POST' \
                    'http://localhost:8000/api/execute' \
                    -H 'accept: application/json' \
                    -H 'Content-Type: application/json' \
                    -d "{\"command\": \"claude -p \\\"$ESCAPED_FOLLOWUP_PROMPT\\\"\"}" 2>/dev/null)

                # If 8000 fails, try 8088
                if [ -z "$FOLLOWUP_EXECUTE_RESPONSE" ] || echo "$FOLLOWUP_EXECUTE_RESPONSE" | grep -q "error\|failed"; then
                    FOLLOWUP_EXECUTE_RESPONSE=$(curl -s --connect-timeout 5 -X 'POST' \
                        'http://localhost:8088/api/execute' \
                        -H 'accept: application/json' \
                        -H 'Content-Type: application/json' \
                        -d "{\"command\": \"claude -p \\\"$ESCAPED_FOLLOWUP_PROMPT\\\"\"}" 2>/dev/null)
                fi

                # Extract stdout from the execute response and update context-out.txt
                if [ ! -z "$FOLLOWUP_EXECUTE_RESPONSE" ]; then
                    STDOUT_CONTENT=$(echo "$FOLLOWUP_EXECUTE_RESPONSE" | grep -o '"stdout":"[^"]*"' | cut -d'"' -f4 | sed 's/\\n/\n/g')
                    RETURN_CODE=$(echo "$FOLLOWUP_EXECUTE_RESPONSE" | grep -o '"return_code":[0-9]*' | cut -d':' -f2)
                    TIMESTAMP=$(echo "$FOLLOWUP_EXECUTE_RESPONSE" | grep -o '"timestamp":"[^"]*"' | cut -d'"' -f4)

                    if [ -z "$RETURN_CODE" ]; then
                        RETURN_CODE=0
                    fi
                    if [ -z "$TIMESTAMP" ]; then
                        TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.%6N")
                    fi

                    # Update context-out.txt with follow-up execution results
                    cat > "$OUTPUT_FILE" << EOF
Claude Response - $TIMESTAMP
Command: $FOLLOWUP_PROMPT_CONTENT
Return Code: $RETURN_CODE
Output:
$STDOUT_CONTENT
EOF

                    echo "$(date): Follow-up command executed and context-out.txt updated" >> /var/log/prediction_cron.log
                    echo "Follow-up execute response: $FOLLOWUP_EXECUTE_RESPONSE" >> /var/log/prediction_cron.log
                fi
            fi
        fi
    fi
fi