#!/usr/bin/env bash
# Generates an original, royalty-free "tense recap" music bed (procedural, no samples) -> assets/music/bed_tense.mp3
# Replace/add your own licensed track in assets/music/ (first file alphabetically is used with --bgm auto).
set -e
OUT="${1:-$(dirname "$0")/../assets/music/bed_tense.mp3}"
DUR="${2:-180}"
R='if(lt(mod(t,9.6),4.8),1,0.7937)'
ffmpeg -y -loglevel error \
 -f lavfi -i "aevalsrc='0.45*sin(2*PI*55*${R}*t)*exp(-5*mod(t,0.6))+0.06*(sin(2*PI*220*${R}*t)+sin(2*PI*261.63*${R}*t)+sin(2*PI*329.63*t)+0.5*sin(2*PI*440*${R}*t))*(0.65+0.35*sin(2*PI*0.125*t))':s=48000:d=${DUR}" \
 -f lavfi -i "aevalsrc='0.5*(random(0)*2-1)*exp(-70*mod(t,0.3))*(0.5+0.5*lt(mod(t,0.6),0.3))':s=48000:d=${DUR}" \
 -f lavfi -i "aevalsrc='0.10*sin(2*PI*880*t+2*sin(2*PI*3*t))*exp(-8*mod(t,2.4))*gt(mod(t,4.8),2.4)':s=48000:d=${DUR}" \
 -filter_complex "[0:a]lowpass=f=1800,aecho=0.6:0.5:300:0.25[a];[1:a]highpass=f=6000,volume=0.6[b];[2:a]aecho=0.7:0.6:450:0.35,volume=0.7[c];[a][b][c]amix=inputs=3:normalize=0,acompressor,loudnorm=I=-20,afade=t=in:d=1.5[o]" \
 -map "[o]" -ac 2 -b:a 160k "$OUT"
echo "$OUT"
