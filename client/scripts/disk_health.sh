#!/bin/ash
# shellcheck shell=dash

# Fråga mig inte hur de funkar, AI har skrivit allt i princip.

# disk_health.sh — offline drive inventory + health + self-test (Alpine/BusyBox ash)
# Safe with smartctl's non-zero statuses.
set -u

print_line() { printf '%s\n' "--------------------------------------------------------------------------------"; }
indent() { sed 's/^/    /'; }


# BusyBox/POSIX-awk compatible: parse RAW_VALUE from smartctl tables
# - Works for "497h+18m+30s"
# - Works for plain integers
# - Works for "44 (Min/Max 10/65)" → takes the first number
get_attr() { # $1=filepath, $2=attr id or name regex (e.g., "^(9|Power_On_Hours|Power_On_Seconds)$")
    awk -v k="$2" '
    /Vendor Specific SMART Attributes/ {in_section=1; next}
    /^SMART/ && in_section {in_section=0}
    in_section && (($1 ~ k) || ($2 ~ k)) {
      v = $10
      if (v ~ /[0-9]+h\+[0-9]+m\+[0-9]+s/) {
        # turn "497h+18m+30s" into seconds using only POSIX features
        gsub(/h\+|m\+|s/, " ", v)
        n = split(v, a)
        v = (a[1]+0)*3600 + (a[2]+0)*60 + (a[3]+0)
      } else if (v ~ /^[0-9]+$/) {
        v += 0
      } else {
        # fallback: first integer substring
        if (match(v, /[0-9]+/)) ;
        else v = 0
      }
    }
    END { if (v == "") v = 0; print v }
    ' "$1" 2>/dev/null
}

smart_severity() { # from key ATA attributes (on parsed /tmp/smart_o)
    o="$1"; sev="PASS"; why=""
    
    ov=$(awk -F: '/overall-health/ {print tolower($2)}' "$o" 2>/dev/null || true)
    [ -n "$ov" ] && echo "$ov" | grep -q failed && { sev="FAIL"; why="$why overall-health-failed"; }
    
    ralloc=$(get_attr "$o" "^(5|Reallocated_Sector_Ct)$")
    repunc=$(get_attr "$o" "^(187|Reported_Uncorrect)$")
    pend=$(get_attr "$o" "^(197|Current_Pending_Sector)$")
    offunc=$(get_attr "$o" "^(198|Offline_Uncorrectable)$")
    crc=$(get_attr "$o" "^(199|UDMA_CRC_Error_Count)$")
    
    if [ "$ralloc" -gt 0 ] || [ "$repunc" -gt 0 ] || [ "$pend" -gt 0 ] || [ "$offunc" -gt 0 ]; then
        sev="FAIL"; why="$why media-errors"
    fi
    if [ "$crc" -gt 0 ] && [ "$sev" = "PASS" ]; then
        sev="WARN"; why="$why crc-link-errors"
    fi
    echo "$sev|$why|ralloc=$ralloc repunc=$repunc pend=$pend offunc=$offunc crc=$crc"
}

echo
print_line
echo "Disk inventory:"
lsblk -o NAME,TYPE,TRAN,SIZE,MODEL,SERIAL,MOUNTPOINT -e 7 \
| awk '$1 !~ /^(ram|loop)/ && $1!="fd0" && $4!="0B"'
print_line

echo "Recent kernel disk messages:"
dmesg | grep -E "sd[a-z]|nvme[0-9]" | tail -n 20 || true
print_line

DISKS=$(lsblk -ndo NAME,TYPE,SIZE | awk '
  $2=="disk" && $1 !~ /^(ram|loop)/ && $1!="fd0" && $3!="0B" {print $1}
')
[ -z "$DISKS" ] && { echo "No disks detected."; exit 0; }

overall_rc=0

for n in $DISKS; do
    dev="/dev/$n"
    echo "Device: $dev"
    MODEL=$(lsblk -ndo MODEL "$dev" 2>/dev/null || true)
    SERIAL=$(lsblk -ndo SERIAL "$dev" 2>/dev/null || true)
    SIZE=$(lsblk -ndo SIZE "$dev" 2>/dev/null || true)
    TRAN=$(lsblk -ndo TRAN "$dev" 2>/dev/null || true)
    ROTF="/sys/block/${n%%[0-9]*}/queue/rotational"
    ROT=$( [ -r "$ROTF" ] && cat "$ROTF" || echo "?" )
    TYPE=$( [ "$ROT" = "1" ] && echo "HDD" || [ "$ROT" = "0" ] && echo "SSD/NVMe" || echo "Unknown" )
    echo "  Model: $MODEL | Serial: ${SERIAL:-N/A} | Size: $SIZE | Bus: ${TRAN:-N/A} | Type: $TYPE"
    
    if echo "$n" | grep -q '^nvme'; then
        ctrl="/dev/${n%%n[0-9]*}"
        
        echo "    → Running short self-test on $ctrl..."
        nvme device-self-test -s 1 "$ctrl" >/tmp/nvme_st_o 2>/tmp/nvme_st_e || true
        nvme smart-log -H "$ctrl" >/tmp/nvme_h 2>/tmp/nvme_e || true
        
        if [ -s /tmp/nvme_h ]; then
            cw=$(nvme smart-log "$ctrl" 2>/dev/null | awk -F: '/critical_warning/{gsub(/ /,"");print $2}')
            me=$(nvme smart-log "$ctrl" 2>/dev/null | awk -F: '/media_errors/{gsub(/ /,"");print $2}')
            ne=$(nvme smart-log "$ctrl" 2>/dev/null | awk -F: '/num_err_log_entries/{gsub(/ /,"");print $2}')
            pu=$(nvme smart-log "$ctrl" 2>/dev/null | awk -F: '/percentage_used/{gsub(/ /,"");print $2}')
            poh=$(nvme smart-log "$ctrl" 2>/dev/null | awk -F: '/power_on_hours/{gsub(/ /,"");print $2}')
            
            sev="PASS"; why=""
            [ "${cw:-0}" != "0" ] && { sev="FAIL"; why="$why critical_warning"; }
            [ "${me:-0}" -gt 0 ] && { sev="FAIL"; why="$why media_errors"; }
            if [ "${pu:-0}" -ge 100 ] && [ "$sev" = "PASS" ]; then sev="FAIL"; why="$why worn_out"; fi
            if [ "${pu:-0}" -ge 80 ]  && [ "$sev" = "PASS" ]; then sev="WARN"; why="$why high_wear"; fi
            if [ "${ne:-0}" -gt 0 ]  && [ "$sev" = "PASS" ]; then sev="WARN"; why="$why controller_errors"; fi
            
            echo "  Health: $sev"
            [ "$sev" != "FAIL" ] && overall_rc=1
            echo "    reasons: ${why:-ok}"
            echo "    Power-on hours: ${poh:-0}  (~$((poh/24/365)) years)"
            echo "    critical_warning: ${cw:-0}"
            echo "    media_errors:     ${me:-0}"
            echo "    err_log_entries:  ${ne:-0}"
            echo "    percentage_used:  ${pu:-0}"
            echo "    SMART (human):"
            sed 's/^/      /' /tmp/nvme_h
            
            if nvme self-test-log "$ctrl" >/tmp/nvme_stlog 2>/dev/null; then
                echo "    Self-test result (most recent):"
                awk '
                  function hex2dec(s,    i,c,v,d){      # BusyBox/POSIX-awk hex → dec
                    d=0
                    for(i=1;i<=length(s);i++){
                      c=substr(s,i,1)
                      if(c>="0" && c<="9") v=c+0
                      else if(c>="a" && c<="f") v=10+index("abcdef",c)-1
                      else if(c>="A" && c<="F") v=10+index("ABCDEF",c)-1
                      else v=0
                      d = d*16 + v
                    }
                    return d
                  }
                  BEGIN {
                    res_map[0]="Completed without error"
                    res_map[1]="Aborted by host"
                    res_map[2]="Interrupted by reset"
                    res_map[3]="Fatal error"
                    res_map[4]="Unknown test error"
                    res_map[5]="Self-test in progress"
                    res_map[6]="Aborted for unknown reason"
                    res_map[7]="Self-test not supported"
                    res_map[15]="No test recorded"
                  }
                  /^Self Test Result\[0\]:/ {in0=1; next}
                  /^Self Test Result\[/ && !/^Self Test Result\[0\]:/ {in0=0}
                  in0 && /Operation Result/ {
                    split($0,a,":"); gsub(/[ \t]/,"",a[2]); code=a[2]+0
                    desc = (code in res_map)?res_map[code]:"Unknown"
                    printf "      Operation Result : %s (code %d)\n", desc, code
                  }
                  in0 && /Self Test Code/ {
                    split($0,a,":"); gsub(/[ \t]/,"",a[2]); code=a[2]+0
                    printf "      Self Test Code   : %s\n", (code==1)?"Short":(code==2)?"Extended":("Code " code)
                  }
                  in0 && /Power on hours/ {
                    split($0,a,":"); p=a[2]
                    gsub(/[ \t]/,"",p)
                    if (p ~ /^0x[0-9A-Fa-f]+$/) {
                      poh=hex2dec(substr(p,3))
                    } else if (p ~ /^[0-9]+$/) {
                      poh=p+0
                    } else {
                      poh=0
                    }
                    yrs = poh/24/365
                    printf "      Power-on hours   : %d (~%.2f years)\n", poh, yrs
                  }
                  END {
                    if (!in0_printed && !seen_any) { }  # quiet
                  }
                ' /tmp/nvme_stlog
            else
                [ -s /tmp/nvme_st_e ] && echo "    Self-test: started (short). Recheck later with: nvme self-test-log $ctrl"
            fi
            
            
        else
            echo "  Health: ERROR"
            overall_rc=1
            echo "    $(head -n 6 /tmp/nvme_e | indent)"
        fi
        
    else
        echo "    → Running short self-test on $dev..."
        if ! smartctl -t short "$dev" >/tmp/s_st 2>/tmp/s_ste; then
            if grep -qi "Unknown USB bridge\|please specify device type" /tmp/s_ste 2>/dev/null; then
                smartctl -d sat -t short "$dev" >/tmp/s_st 2>/tmp/s_ste || true
            fi
        fi
        
        end=$(( $(date +%s) + 130 ))
        while [ "$(date +%s)" -lt "$end" ]; do
            smartctl -c "$dev" 2>/dev/null | grep -q "Self-test routine in progress" && { sleep 5; continue; }
            break
        done
        
        smartctl -H -A -l error -l selftest "$dev" >/tmp/smart_o 2>/tmp/smart_e || true
        if [ ! -s /tmp/smart_o ] || grep -qi "Unknown USB bridge\|please specify device type" /tmp/smart_e 2>/dev/null; then
            smartctl -d sat -H -A -l error -l selftest "$dev" >/tmp/smart_o 2>/tmp/smart_e || true
        fi
        
        if [ -s /tmp/smart_o ]; then
            poh=$(get_attr /tmp/smart_o "^(Power_On_Hours|Power_On_Seconds)$")
            
            # If it looks like seconds (very large), convert to hours
            [ "$poh" -gt 100000 ] && poh=$((poh/3600))
      IFS="|" read -r sev why extras <<EOF
$(smart_severity /tmp/smart_o)
EOF
            [ -z "$why" ] && why="ok"
            
            ata_err_cnt=$(awk -F: '/ATA Error Count/ {gsub(/^[ \t]+/,"",$2); print $2+0}' /tmp/smart_o 2>/dev/null || echo 0)
            [ "$ata_err_cnt" -gt 0 ] && [ "$sev" = "PASS" ] && { sev="WARN"; why="$why ata_error_log"; }
            
            echo "  Health: $sev"
            [ "$sev" != "FAIL" ] && overall_rc=1
            echo "    reasons: $why"
            echo "    $extras"
            echo "    Power-on hours: ${poh:-0}  (~$((poh/24/365)) years)"
            echo "    ata_error_log: $ata_err_cnt"
            
            if [ "$ata_err_cnt" -gt 0 ]; then
                echo "    Recent ATA errors (drive shows last 5):"
                awk '/^Error [0-9]+ occurred/ || /^Error: / {print "      " $0}' /tmp/smart_o | head -n 20
            fi
            
            echo "    Self-test results:"
            awk '/Self-test execution status|# 1/ {print "      " $0}' /tmp/smart_o
            
            echo "    Key SMART attributes:"
            awk '
              /Vendor Specific SMART Attributes/ {in_attr=1; next}
              /^SMART/ && in_attr {in_attr=0}
              in_attr {
                id=$1; name=$2
                want=0
                if (id ~ /^(5|187|196|197|198|199)$/) want=1
                if (name ~ /(Reallocated_Sector_Ct|Reported_Uncorrect|Uncorrect|Current_Pending_Sector|Offline_Uncorrectable|UDMA_CRC_Error_Count)/) want=1
                if (!want) next

                # Rebuild RAW_VALUE from columns 10..NF (may include spaces/parentheses)
                raw=""
                for (i=10; i<=NF; i++) raw = raw (i==10 ? "" : " ") $i

                # Normalize RAW to a number (handles "497h+18m+30s" and "0 (2000 0)")
                val=0
                tmp=raw
                if (tmp ~ /[0-9]+h\+[0-9]+m\+[0-9]+s/) {
                  gsub(/h\+|m\+|s/, " ", tmp)
                  n=split(tmp,a)
                  val = (a[1]+0)*3600 + (a[2]+0)*60 + (a[3]+0)
                } else if (match(tmp, /^[0-9]+/)) {
                  val = substr(tmp, RSTART, RLENGTH) + 0
                } else if (match(tmp, /[0-9]+/)) {
                  val = substr(tmp, RSTART, RLENGTH) + 0
                }

                printf "      %-26s raw=%s\n", name, val
              }
            ' /tmp/smart_o
        else
            echo "  Health: ERROR"
            overall_rc=1
            echo "    $(sed -n '1,8p' /tmp/smart_e | indent)"
        fi
    fi
    
    print_line
done

exit "$overall_rc"
