echo "`dig +short slack.com`\n`dig +short api.slack.com`" | sort -t . -n -k 1,1 | jq -Rn '[inputs]'