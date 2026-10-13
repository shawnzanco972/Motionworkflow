// Add-avatar and add-voice dialogs, shared by the Presenter page and the Assets page.

import { $, $$, api, esc, icon, openDialog, refreshLibrary, refreshStatus, toast } from "./core.js";

const READ_ALOUD = "Hi, this is my voice for my videos. I talk about the things I care about, " +
  "the way I would explain them to a friend. Some days are fast and loud, others are calm and slow, " +
  "and that's fine. Thanks for listening, and see you in the next one.";

const CONSENT = `<label class="switch"><input type="checkbox" name="consent"><span class="track"></span>
  <span class="txt"><b>This is me, or the person agreed</b><span>Only use faces and voices you have the right to use. AI-made people should be labelled when you post.</span></span></label>`;

function preview(file) {
  const url = URL.createObjectURL(file);
  if (file.type.startsWith("image/")) return `<img src="${url}" alt="" style="max-height:220px;border-radius:12px;margin:auto">`;
  if (file.type.startsWith("video/")) return `<video src="${url}" controls muted playsinline style="max-height:220px;border-radius:12px;margin:auto"></video>`;
  return `<audio src="${url}" controls style="width:100%"></audio>`;
}

async function upload(kind, form, file, extra = {}) {
  const fd = new FormData();
  fd.append("file", file, file.name || (kind === "voices" ? "recording.webm" : "upload"));
  fd.append("name", form.elements.name.value);
  fd.append("consent", form.elements.consent.checked ? "true" : "false");
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const item = await api(`/api/library/${kind}`, { method: "POST", body: fd });
  await refreshLibrary();
  refreshStatus();
  return item;
}

export function addAvatarDialog() {
  let file = null;
  return new Promise((resolve) => {
    openDialog({
      title: "Add an avatar",
      iconName: "presenter",
      wide: true,
      body: `
        <div class="drop" data-drop>
          <input type="file" accept="image/*,video/*" aria-label="Photo or video">
          <div class="ico">${icon("camera")}</div>
          <div><b>Drop a photo or a short video</b><span>JPG, PNG, WebP · or MP4/MOV/WebM, 10-20 s</span></div>
        </div>
        <div data-preview style="display:grid"></div>
        <ul class="tips">
          <li>${icon("check")}<span><b>Best and cheapest:</b> 10-20 s of video of you looking at the camera, mouth mostly closed. It is lip-synced to your voice.</span></li>
          <li>${icon("check")}<span><b>Photo:</b> facing the camera, shoulders up, even light, plain background, no hands near the face.</span></li>
          <li>${icon("check")}<span>Frame it the way you want the video framed (vertical for TikTok/Reels).</span></li>
        </ul>
        <div class="field"><label class="label" for="avName">Name</label><input class="input" id="avName" name="name" placeholder="Me, desk setup"></div>
        ${CONSENT}
        <div data-error></div>`,
      actions: [{ label: "Cancel", kind: "ghost" }, { label: `${icon("upload")}Save avatar`, kind: "primary", type: "button", id: "avSave" }],
      onOpen: (d) => {
        const form = $("form", d);
        const input = $("[data-drop] input", d);
        const take = (f) => { file = f; $("[data-preview]", d).innerHTML = preview(f); if (!form.elements.name.value) form.elements.name.value = f.name.replace(/\.[^.]+$/, "").slice(0, 40); };
        input.onchange = () => input.files[0] && take(input.files[0]);
        const zone = $("[data-drop]", d);
        zone.ondragover = (e) => { e.preventDefault(); zone.classList.add("over"); };
        zone.ondragleave = () => zone.classList.remove("over");
        zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove("over"); e.dataTransfer.files[0] && take(e.dataTransfer.files[0]); };
        $("#avSave", d).onclick = async (e) => {
          const btn = e.currentTarget;
          if (!file) { $("[data-error]", d).innerHTML = `<div class="notice bad">${icon("alert")}<span>Choose a photo or a video first.</span></div>`; return; }
          btn.disabled = true;
          btn.innerHTML = "Saving…";
          try {
            const item = await upload("avatars", form, file);
            toast(`Saved ${item.name}`, "good");
            d.close("__close");
            resolve(item);
          } catch (err) {
            $("[data-error]", d).innerHTML = `<div class="notice bad">${icon("alert")}<span>${esc(err.message)}</span></div>`;
            btn.disabled = false;
            btn.innerHTML = `${icon("upload")}Save avatar`;
          }
        };
      },
    }).then(() => resolve(null));
  });
}

export function addVoiceDialog() {
  let file = null;
  let recorder = null;
  let stream = null;
  let raf = 0;
  let started = 0;
  let tick = 0;
  const stop = () => {
    cancelAnimationFrame(raf);
    clearInterval(tick);
    if (recorder && recorder.state !== "inactive") recorder.stop();
    stream?.getTracks().forEach((t) => t.stop());
  };
  return new Promise((resolve) => {
    openDialog({
      title: "Add your voice",
      iconName: "mic",
      wide: true,
      body: `
        <div class="seg full" role="tablist">
          <input type="radio" name="mode" id="vmRec" value="record" checked><label for="vmRec">${icon("mic")}Record now</label>
          <input type="radio" name="mode" id="vmUp" value="upload"><label for="vmUp">${icon("upload")}Upload a file</label>
        </div>
        <div data-pane="record" class="recorder">
          <div class="read-card" data-read>${READ_ALOUD}</div>
          <div class="rec-row">
            <button type="button" class="rec-btn" data-rec aria-label="Start recording">${icon("mic", "xl")}</button>
            <div style="flex:1;display:grid;gap:8px">
              <div class="rec-time" data-time>0:00</div>
              <div class="level" aria-hidden="true"><i data-level></i></div>
            </div>
          </div>
          <div class="hint">Read the text above in your normal voice, in a quiet room, 15-25 seconds. Hold the phone or mic the same distance the whole time.</div>
        </div>
        <div data-pane="upload" hidden>
          <div class="drop" data-drop>
            <input type="file" accept="audio/*,video/*" aria-label="Voice recording">
            <div class="ico">${icon("wave")}</div>
            <div><b>Drop a recording of your voice</b><span>MP3, WAV, M4A or a video · 10-60 s of just you talking</span></div>
          </div>
          <div class="field" style="margin-top:12px"><label class="label" for="vTr">What you say in it <span class="opt">optional, improves cloning</span></label>
            <textarea class="textarea" id="vTr" name="transcript" rows="3"></textarea></div>
        </div>
        <div data-preview style="display:grid"></div>
        <div class="field"><label class="label" for="vName">Name</label><input class="input" id="vName" name="name" placeholder="My voice"></div>
        ${CONSENT}
        <div data-error></div>`,
      actions: [{ label: "Cancel", kind: "ghost" }, { label: `${icon("check")}Save voice`, kind: "primary", type: "button", id: "vSave" }],
      onOpen: (d) => {
        const form = $("form", d);
        const setMode = () => { const m = form.elements.mode.value; $$("[data-pane]", d).forEach((p) => (p.hidden = p.dataset.pane !== m)); };
        $$('input[name="mode"]', d).forEach((r) => (r.onchange = setMode));
        const take = (f, recorded = false) => {
          file = f;
          $("[data-preview]", d).innerHTML = preview(f);
          if (!form.elements.name.value) form.elements.name.value = recorded ? "My voice" : f.name.replace(/\.[^.]+$/, "").slice(0, 40);
          if (recorded) form.elements.transcript.value = READ_ALOUD;
        };
        const input = $("[data-drop] input", d);
        input.onchange = () => input.files[0] && take(input.files[0]);
        const zone = $("[data-drop]", d);
        zone.ondragover = (e) => { e.preventDefault(); zone.classList.add("over"); };
        zone.ondragleave = () => zone.classList.remove("over");
        zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove("over"); e.dataTransfer.files[0] && take(e.dataTransfer.files[0]); };

        const btn = $("[data-rec]", d);
        btn.onclick = async () => {
          if (recorder && recorder.state === "recording") { stop(); return; }
          if (!navigator.mediaDevices?.getUserMedia) { toast("This browser can't record here; upload a file instead.", "bad"); return; }
          try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
          } catch (err) {
            toast("Microphone access was blocked. Allow it in the browser, or upload a file.", "bad");
            return;
          }
          const chunks = [];
          recorder = new MediaRecorder(stream);
          recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
          recorder.onstop = () => {
            btn.classList.remove("on");
            btn.innerHTML = icon("mic", "xl");
            btn.setAttribute("aria-label", "Record again");
            const type = recorder.mimeType || "audio/webm";
            const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
            take(new File(chunks, `recording.${ext}`, { type }), true);
          };
          const ctxA = new AudioContext();
          const analyser = ctxA.createAnalyser();
          ctxA.createMediaStreamSource(stream).connect(analyser);
          const buf = new Uint8Array(analyser.fftSize);
          const draw = () => {
            analyser.getByteTimeDomainData(buf);
            let peak = 0;
            for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
            $("[data-level]", d).style.width = `${Math.min(100, (peak / 128) * 160)}%`;
            raf = requestAnimationFrame(draw);
          };
          draw();
          started = Date.now();
          tick = setInterval(() => {
            const s = Math.floor((Date.now() - started) / 1000);
            $("[data-time]", d).textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
            if (s >= 60) stop();
          }, 250);
          recorder.start();
          btn.classList.add("on");
          btn.innerHTML = icon("stop", "xl");
          btn.setAttribute("aria-label", "Stop recording");
        };

        $("#vSave", d).onclick = async (e) => {
          const save = e.currentTarget;
          if (!file) { $("[data-error]", d).innerHTML = `<div class="notice bad">${icon("alert")}<span>Record or choose a recording first.</span></div>`; return; }
          save.disabled = true;
          save.innerHTML = "Cleaning up the audio…";
          try {
            const item = await upload("voices", form, file, { transcript: form.elements.transcript.value });
            toast(`Saved ${item.name}`, "good");
            d.close("__close");
            resolve(item);
          } catch (err) {
            $("[data-error]", d).innerHTML = `<div class="notice bad">${icon("alert")}<span>${esc(err.message)}</span></div>`;
            save.disabled = false;
            save.innerHTML = `${icon("check")}Save voice`;
          }
        };
      },
    }).then(() => { stop(); resolve(null); });
  });
}
