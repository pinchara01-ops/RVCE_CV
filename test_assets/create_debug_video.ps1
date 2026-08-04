$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$speech = Join-Path $PSScriptRoot "debug_processing_speech.wav"
$video = Join-Path $PSScriptRoot "debug_processing_video.mp4"

Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.SetOutputToWaveFile($speech)
$voice.Speak("A person stands beside a red box. The person reaches toward the box and moves it across the table. A bell rings near the end of the demonstration.")
$voice.Dispose()

ffmpeg -y -f lavfi -i "color=c=lightblue:s=640x360:r=24:d=40" -i $speech -f lavfi -i "sine=frequency=880:sample_rate=48000:duration=1" -filter_complex "[0:v]drawbox=x=0:y=280:w=640:h=80:color=brown:t=fill,drawbox=x=120:y=90:w=55:h=120:color=navy:t=fill,drawbox=x=130:y=45:w=35:h=45:color=tan:t=fill,drawbox=x='if(lt(t,12),390,if(lt(t,24),390-(t-12)*15,210))':y=235:w=70:h=45:color=red:t=fill[v];[1:a]apad=pad_dur=40[voice];[2:a]adelay=32000|32000,apad=pad_dur=40[bell];[voice][bell]amix=inputs=2:duration=longest:normalize=0[a]" -map "[v]" -map "[a]" -t 40 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $video
if ($LASTEXITCODE -ne 0) { throw "FFmpeg test-video generation failed" }
Write-Output $video
