import os, base64, json, requests, wave, asyncio, time, sys
T="เด็กพวกนี้ไม่รู้เลยว่า ทริปเข้าป่าครั้งนี้ จะกลายเป็นฝันร้ายที่สุดในชีวิต เพราะสิ่งที่รออยู่ข้างใน ไม่ใช่เห็ดธรรมดา"
K=os.environ["GEMINI_TTS_API_KEY_2"]
def gem(model, voice, out, style="อ่านแบบนักเล่าสรุปหนังสายรีแคป เร็ว ตื่นเต้น น่าติดตาม เป็นธรรมชาติ: "):
    t=time.time()
    r=requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",headers={"x-goog-api-key":K},json={
      "contents":[{"parts":[{"text":style+T}]}],
      "generationConfig":{"responseModalities":["AUDIO"],"speechConfig":{"voiceConfig":{"prebuiltVoiceConfig":{"voiceName":voice}}}}},timeout=120)
    if r.status_code!=200: print(model,voice,r.status_code,r.text[:300]); return
    d=r.json(); p=d["candidates"][0]["content"]["parts"][0]["inlineData"]
    pcm=base64.b64decode(p["data"])
    with wave.open(out,"wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    print(model,voice,p["mimeType"],round(len(pcm)/48000,2),"s",round(time.time()-t,1),"s gen", d.get("usageMetadata"))
def el(model, vid, out):
    r=requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=mp3_44100_128",headers={"xi-api-key":os.environ["ELEVENLABS_API_KEY"]},json={"text":T,"model_id":model,"language_code":"th"},timeout=120)
    if r.status_code!=200: print(model,r.status_code,r.text[:300]); return
    open(out,"wb").write(r.content); print(model,"ok",len(r.content))
async def edge(v,out):
    import edge_tts
    await edge_tts.Communicate(T,v,rate="+15%").save(out); print("edge",v,"ok")
which=sys.argv[1]
if which=="gem":
  for m in ["gemini-3.1-flash-tts-preview","gemini-3.8-flash-tts","gemini-2.5-pro-preview-tts"]:
    for v in ["Charon","Kore"]:
      gem(m,v,f"gem_{m}_{v}.wav")
if which=="el":
  el("eleven_v3","JBFqnCBsd6RMkjVDRZzb","el_v3_george.mp3")
  el("eleven_multilingual_v2","JBFqnCBsd6RMkjVDRZzb","el_v2_george.mp3")
if which=="edge":
  asyncio.run(edge("th-TH-NiwatNeural","edge_niwat.mp3")); asyncio.run(edge("th-TH-PremwadeeNeural","edge_prem.mp3"))
