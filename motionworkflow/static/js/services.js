// The Create pages, declared as data. forms.js renders them.

import { icon, state } from "./core.js";

const ASPECTS = [["9:16", "9:16", "Vertical"], ["16:9", "16:9", "Wide"], ["1:1", "1:1", "Square"]];
const STYLES = [
  "vibrant 3D animated film style, soft lighting", "photoreal cinematic, shallow depth of field", "anime, clean line art, bright colors",
  "claymation stop-motion, handmade textures", "retro 90s cartoon, bold outlines", "LEGO brick world, toy photography",
  "comic book, halftone shading", "watercolor storybook illustration", "found-footage documentary, handheld",
].map((s) => [s, s.split(",")[0].replace(/^\w/, (c) => c.toUpperCase())]);

const avatarKind = (values) => state.library.avatars.find((a) => a.id === values.avatar_id)?.kind;

export const SERVICES = {
  presenter: {
    id: "presenter", workflow: "presenter", icon: "presenter", color: "c1",
    eyebrow: "Presenter", title: "Talk about anything, as you",
    steps: [["Script"], ["Your voice"], ["You approve", true], ["Your avatar talks"], ["Captions & cutaways"], ["Posts"]],
    intro: "Pick a topic. We write a script, speak it in <b>your cloned voice</b> and animate <b>your face</b> saying it, with captions and optional cutaways. You approve the script and voice before any video is made.",
    cta: "Write script & voice", ctaShort: "Start",
    gate: "You'll hear your voice and read the script first. Animating your avatar (the expensive part) waits for your approval.",
    youGet: "A vertical (or wide) talking video with burned-in captions, the voice track, the script, posts for TikTok / X / LinkedIn and a thumbnail.",
    sections: [
      { title: "What's it about?", desc: "A topic is enough. Claude writes it to be understood on one hearing.", fields: [
        { type: "textarea", name: "topic", label: "Topic", big: true, rows: 3, placeholder: "e.g. Why compound interest feels slow, then suddenly fast" },
        { type: "chips", target: "topic", options: ["3 habits that actually improve sleep", "How I'd learn to code in 2026", "The 50/30/20 budget, explained", "Why your houseplants keep dying"] },
        { type: "row", fields: [
          { type: "range", name: "seconds", label: "Length", min: 15, max: 120, step: 5, default: 30, format: (v) => `${v} s` },
          { type: "select", name: "tone", label: "Tone", default: "friendly expert", options: [["friendly expert", "Friendly expert"], ["energetic", "Energetic"], ["calm and thoughtful", "Calm"], ["funny", "Funny"], ["straight to the point", "Straight to the point"]] },
        ] },
        { type: "row", fields: [
          { type: "text", name: "audience", label: "Who is it for?", optional: true, placeholder: "Beginners, small business owners…" },
          { type: "select", name: "language", label: "Language", default: "English", options: [["English", "English"], ["Spanish", "Spanish"], ["French", "French"], ["German", "German"], ["Portuguese", "Portuguese"], ["Hebrew", "Hebrew"]],
            hint: "Voice cloning models are strongest in English." },
        ] },
        { type: "html", html: `<details class="more"><summary>${icon("chev")}Use my own script instead</summary><div class="inner">` },
        { type: "textarea", name: "script", label: "Your script", rows: 6, placeholder: "Write what you want to say. Each sentence becomes a line you can re-record on its own." },
        { type: "html", html: `</div></details>` },
      ] },
      { title: "You", desc: "Saved once, reused in every video. Only your own face and voice, or people who said yes.", fields: [
        { type: "avatar", name: "avatar_id", label: "Avatar", hint: "A short video of you lip-synced is the most lifelike and the cheapest. A photo also works." },
        { type: "voicepick", name: "voice_id", label: "Voice" },
      ] },
      { title: "Look", fields: [
        { type: "seg", name: "aspect_ratio", label: "Format", default: "9:16", options: ASPECTS },
        { type: "switches", items: [
          { type: "switch", name: "captions", label: "Captions", hint: "Whole lines, key word lit, for muted viewers.", default: true },
          { type: "switch", name: "broll", label: "Cutaway pictures", hint: "Cut to an illustration on about one line in three.", default: false },
        ] },
        { type: "row", fields: [
          { type: "select", name: "caption_style", label: "Caption style", default: "bold", options: [["bold", "Bold white"], ["yellow", "Bold yellow"], ["classic", "Classic subtitles"]] },
          { type: "file", name: "music", label: "Background music", optional: true, accept: "audio/*", icon: "wave", cta: "Add a track", types: "Ducked under your voice" },
        ] },
      ] },
      { title: "Advanced", advanced: true, fields: [
        { type: "switches", items: [
          { type: "switch", name: "review", label: "Approve script and voice first", hint: "Recommended: nothing is animated until you say so.", default: true },
          { type: "switch", name: "review_cut", label: "Fresh-eyes score", hint: "Claude scores the finished cut from frames only (~$0.03).", default: true },
        ] },
        { type: "row", fields: [
          { type: "model", name: "voice_model", label: "Voice model", kinds: ["voice_clone", "tts"] },
          { type: "model", name: "avatar_model", label: "Avatar model", kinds: ["talking_head", "lipsync"] },
        ] },
        { type: "model", name: "image_model", label: "Cutaway picture model", kinds: ["image"] },
      ] },
    ],
    toParams(v) {
      const p = { ...v };
      if (p.voice_id) delete p.voice;
      return p;
    },
    counts(v) {
      return { avatar_is_video: avatarKind(v) === "video", voice_sample: v.voice_id ? 1 : 0 };
    },
    validate(p) {
      if (!(p.topic || "").trim() && !(p.script || "").trim()) return "Write a topic or paste your script.";
      if (!p.avatar_id) return "Add an avatar first: a photo or a short video of you.";
      return null;
    },
    notices(v) {
      const out = [];
      if (!state.library.avatars.length) out.push(`<div class="notice info">${icon("presenter")}<span>Add your avatar once and it's saved for every video.</span></div>`);
      if (!v.voice_id) out.push(`<div class="notice info">${icon("mic")}<span>Using a stock voice. Record 20 seconds of yours to sound like you.</span></div>`);
      return out;
    },
  },

  short: {
    id: "short", workflow: "short", icon: "film", color: "c2",
    eyebrow: "Short Maker", title: "From an idea to a finished short",
    steps: [["Script"], ["Keyframes"], ["Storyboard (animated)", true], ["Motion"], ["Voice & captions"], ["Score & posts"]],
    intro: "Claude writes a hook-first script, we make the pictures, voice and captions, and cut it into a vertical video with posts ready to go. Slideshow costs cents; animated pauses at the storyboard before spending on motion.",
    cta: "Create short", ctaShort: "Create",
    gate: "Animated shorts stop at the storyboard so you can fix any shot before paying for motion.",
    youGet: "Final MP4 with voice and captions, keyframes, script, posts for TikTok / X / LinkedIn, thumbnail and (with a Claude key) a reviewer's score.",
    sections: [
      { title: "The idea", desc: "One sentence is enough. Or paste your own script.", fields: [
        { type: "textarea", name: "idea", label: "Video idea", big: true, rows: 3, placeholder: "A pigeon who secretly runs a hedge fund from a park bench" },
        { type: "chips", target: "idea", options: ["A pigeon who secretly runs a hedge fund", "Cats explain taxes badly", "Grandma becomes a famous DJ overnight", "If dogs had LinkedIn", "A potato's motivational speech", "Medieval knight discovers Wi-Fi"] },
        { type: "html", html: `<details class="more"><summary>${icon("chev")}Use my own script instead</summary><div class="inner">` },
        { type: "textarea", name: "script", label: "One shot per line", rows: 5, placeholder: "Nobody suspects the pigeon. | a pigeon in a tiny suit on a park bench | slow push-in", hint: "<code>narration | visual prompt | motion</code> (the last two are optional)" },
        { type: "html", html: `</div></details>` },
      ] },
      { title: "Format", fields: [
        { type: "choices", name: "mode", label: "How it moves", default: "slideshow", options: [["slideshow", "Slideshow", "Camera moves over stills · cents"], ["animated", "Animated", "AI video per shot · after you approve"]] },
        { type: "row", fields: [
          { type: "number", name: "shots", label: "Shots", default: 5, min: 1, max: 12 },
          { type: "number", name: "shot_seconds", label: "Seconds per shot", default: 5, min: 2, max: 10, step: 0.5 },
        ] },
        { type: "seg", name: "aspect_ratio", label: "Format", default: "9:16", options: ASPECTS },
        { type: "row", fields: [
          { type: "select", name: "style", label: "Look", options: STYLES },
          { type: "select", name: "tone", label: "Tone", default: "funny", options: ["funny", "absurd", "wholesome", "dramatic", "educational", "motivational", "spooky"].map((t) => [t, t[0].toUpperCase() + t.slice(1)]) },
        ] },
      ] },
      { title: "Voice and captions", fields: [
        { type: "switches", items: [
          { type: "switch", name: "voiceover", label: "Voiceover", default: true },
          { type: "switch", name: "captions", label: "Captions", default: true },
        ] },
        { type: "row", fields: [
          { type: "stockvoice", name: "voice", label: "Voice" },
          { type: "select", name: "caption_style", label: "Caption style", default: "bold", options: [["bold", "Bold white"], ["yellow", "Bold yellow"], ["classic", "Classic subtitles"]] },
        ] },
        { type: "row", fields: [
          { type: "file", name: "character", label: "Recurring character", optional: true, accept: "image/*", icon: "image", cta: "Add a character image", types: "Kept the same in every shot" },
          { type: "file", name: "music", label: "Background music", optional: true, accept: "audio/*", icon: "wave", cta: "Add a track", types: "Ducked under the voice" },
        ] },
      ] },
      { title: "Advanced", advanced: true, fields: [
        { type: "switches", items: [
          { type: "switch", name: "review", label: "Storyboard review", hint: "Animated mode pauses for your approval.", default: true },
          { type: "switch", name: "review_cut", label: "Fresh-eyes score", hint: "~$0.03 with a Claude key.", default: true },
        ] },
        { type: "row", fields: [
          { type: "model", name: "image_model", label: "Keyframe model", kinds: ["image", "image_edit"] },
          { type: "model", name: "video_model", label: "Animation model", kinds: ["image_to_video"] },
        ] },
        { type: "row", fields: [
          { type: "model", name: "tts_model", label: "Voice model", kinds: ["tts"] },
          { type: "select", name: "resolution", label: "Video resolution", options: [["", "Model default"], ["480p", "480p"], ["720p", "720p"], ["1080p", "1080p"]] },
        ] },
      ] },
    ],
    validate: (p) => (!(p.idea || "").trim() && !(p.script || "").trim() ? "Describe the idea or paste a script." : null),
  },

  image: {
    id: "image", workflow: "image", icon: "image", color: "c3",
    eyebrow: "Image", title: "Pictures from a sentence",
    intro: "Text to image from about $0.003 a picture, or add reference images to edit them or keep a character consistent.",
    cta: "Generate", youGet: "Full-size images you can download, reuse as a start frame for Video, or as a recurring character.",
    sections: [
      { title: "Describe it", fields: [
        { type: "textarea", name: "prompt", label: "Prompt", big: true, placeholder: "A corgi in a business suit giving a TED talk, dramatic stage lighting" },
        { type: "row", fields: [
          { type: "seg", name: "num_images", label: "How many", default: "1", options: [["1", "1"], ["2", "2"], ["4", "4"], ["8", "8"]] },
          { type: "seg", name: "aspect_ratio", label: "Format", default: "1:1", options: [["1:1", "1:1"], ["9:16", "9:16"], ["16:9", "16:9"], ["4:3", "4:3"]] },
        ] },
      ] },
      { title: "References", desc: "Optional: edit a picture, or keep the same person, product or character.", fields: [
        { type: "file", name: "refs", multiple: true, accept: "image/*", icon: "image", cta: "Add reference images", types: "JPG, PNG or WebP" },
      ] },
      { title: "Advanced", advanced: true, fields: [
        { type: "row", fields: [
          { type: "model", name: "model", label: "Model", kinds: ["image", "image_edit"] },
          { type: "number", name: "seed", label: "Seed", optional: true },
        ] },
      ] },
    ],
    toParams: (v) => ({ ...v, num_images: Number(v.num_images || 1) }),
    validate: (p) => (!(p.prompt || "").trim() ? "Write a prompt." : null),
  },

  video: {
    id: "video", workflow: "video", icon: "video", color: "c4",
    eyebrow: "Video", title: "A clip from text or a picture",
    intro: "Describe a shot, or bring a still and say how it should move. Draft cheaply first and only pay for a premium final when it's worth it.",
    cta: "Generate video", youGet: "An MP4 clip. With a draft first, the final waits for your approval.",
    sections: [
      { title: "The shot", fields: [
        { type: "textarea", name: "prompt", label: "Prompt", big: true, placeholder: "A raccoon DJ at a rooftop party, camera orbits slowly, neon lights", hint: "With a start picture, describe the change: one action, one slow camera move." },
        { type: "file", name: "image", label: "Start picture", optional: true, accept: "image/*", icon: "image", cta: "Animate a picture", types: "The clip starts on this frame" },
      ] },
      { title: "Format", fields: [
        { type: "row", fields: [
          { type: "seg", name: "duration", label: "Length", default: "5", options: [["5", "5 s"], ["10", "10 s"]] },
          { type: "seg", name: "aspect_ratio", label: "Format", default: "9:16", options: ASPECTS },
        ] },
        { type: "row", fields: [
          { type: "select", name: "resolution", label: "Resolution", options: [["", "Model default"], ["480p", "480p"], ["720p", "720p"], ["1080p", "1080p"]] },
          { type: "switch", name: "audio", label: "Generate sound", hint: "Only some models; costs more.", default: false },
        ] },
        { type: "switch", name: "draft_first", label: "Cheap draft first, then a final after I approve", hint: "Worth it for risky ideas; a draft you then finish costs more than going straight to the final.", default: false },
        { type: "row", show: (v) => v.draft_first, name: "finalrow", fields: [
          { type: "select", name: "final_tier", label: "Final quality", default: "premium", options: [["premium", "Premium"], ["standard", "Standard"]] },
          { type: "select", name: "final_resolution", label: "Final resolution", options: [["", "Model default"], ["720p", "720p"], ["1080p", "1080p"]] },
        ] },
      ] },
      { title: "Advanced", advanced: true, fields: [{ type: "model", name: "model", label: "Model", kinds: ["video", "image_to_video"] }] },
    ],
    toParams(v) {
      const p = { ...v, duration: Number(v.duration || 5) };
      if (!p.draft_first) { delete p.final_tier; delete p.final_resolution; }
      delete p.draft_first;
      return p;
    },
    validate: (p) => (!(p.prompt || "").trim() ? "Write a prompt." : null),
  },

  voice: {
    id: "voice", workflow: "voice", icon: "wave", color: "c5",
    eyebrow: "Voiceover", title: "Words into a voice",
    intro: "Paste a line or a whole narration. Use a stock voice, or <b>your own cloned voice</b> from your library.",
    cta: "Make voiceover", youGet: "An audio file you can download or use anywhere.",
    sections: [
      { title: "The words", fields: [
        { type: "textarea", name: "text", label: "Script", big: true, rows: 6, placeholder: "Nobody suspects the pigeon in the tiny suit.", hint: "Write for one hearing: short sentences, about two words a second." },
      ] },
      { title: "The voice", fields: [{ type: "voicepick", name: "voice_id", label: "Voice" }] },
      { title: "Advanced", advanced: true, fields: [{ type: "model", name: "model", label: "Model", kinds: ["tts", "voice_clone"] }] },
    ],
    toParams(v) { const p = { ...v }; if (p.voice_id) delete p.voice; return p; },
    counts: (v) => ({ voice_sample: v.voice_id ? 1 : 0 }),
    validate: (p) => (!(p.text || "").trim() ? "Write the words to speak." : null),
  },

  swap: {
    id: "swap", workflow: "swap", icon: "swap", color: "c6",
    eyebrow: "Character Swap · Genjutsu", title: "Your scene, a new character",
    steps: [["Prep (optional)"], ["Review prep", true], ["Draft"], ["Approve", true], ["Final with original audio"]],
    intro: "Replace the person in a clip of up to 30 s with your character. The final keeps the clip's complete original audio. Optional Genjutsu prep (depth + SAM 3 masks, or a face mesh) for the cleanest swaps.",
    cta: "Create swap", gate: "Drafts and Genjutsu prep stop for your review before the next paid step.",
    youGet: "A draft with the original audio, then the final after you approve (or one render with “skip the draft”).",
    sections: [
      { title: "The clip and the character", fields: [
        { type: "file", name: "video", label: "Source video", accept: "video/*", icon: "video", cta: "Add the clip", types: "Up to 30 s; longer clips are trimmed" },
        { type: "file", name: "refs", label: "Character reference", multiple: true, accept: "image/*,video/*", icon: "image", cta: "Add the character", types: "An image (or a short identity video for Seedance)" },
        { type: "textarea", name: "prompt", label: "Direction", optional: true, rows: 3, placeholder: "Replace the man with the character from @Image1. Keep the background, camera, lighting and lip-sync exactly." },
      ] },
      { title: "Render", fields: [
        { type: "model", name: "model", label: "Engine", kinds: ["swap"] },
        { type: "switch", name: "direct", label: "Skip the draft", hint: "One render at final quality: cheaper overall, no preview first.", default: false },
        { type: "row", fields: [
          { type: "select", name: "draft_resolution", label: "Draft resolution", options: [["", "Model default"], ["480p", "480p"], ["580p", "580p"], ["720p", "720p"]] },
          { type: "select", name: "final_resolution", label: "Final resolution", options: [["", "Model best"], ["720p", "720p"], ["580p", "580p"], ["480p", "480p"]] },
        ] },
      ] },
      { title: "Genjutsu prep", advanced: true, fields: [
        { type: "html", html: `<p class="hint" style="margin-top:0">Runs Genjutsu's own preparation first (needs <code>bash scripts/install-skills.sh --with-genjutsu-env</code> and a Replicate token), then stops so you can watch the whole prepared clip. Seedance engine only.</p>` },
        { type: "row", fields: [
          { type: "select", name: "prep", label: "Prep", options: [["none", "None"], ["genjutsu-depth", "Depth + SAM 3 mask"], ["genjutsu-face-mesh", "Fast · face mesh"], ["genjutsu-depth-mesh", "Depth + face mesh"]] },
          { type: "text", name: "subject", label: "Subject to mask", default: "person" },
        ] },
        { type: "switch", name: "prepared", label: "The clip is already a Genjutsu seedance-input.mp4", default: false },
        { type: "file", name: "original", label: "Untouched original clip", optional: true, accept: "video/*,audio/*", cta: "Add the original", types: "Its audio goes on the final" },
      ] },
    ],
    validate: (p, ctx) => (!ctx.files.video?.length ? "Add the source video." : !ctx.files.refs?.length ? "Add a character reference." : null),
    after(form, ctx) {
      // The estimate needs the clip length; read it from the browser.
      const orig = ctx.changed;
      let seen = null;
      ctx.changed = () => {
        const v = ctx.files.video?.[0];
        if (v && v !== seen) {
          seen = v;
          const el = document.createElement("video");
          el.preload = "metadata";
          el.onloadedmetadata = () => { ctx.sourceSeconds = Math.min(30, el.duration || 10); URL.revokeObjectURL(el.src); orig(); };
          el.src = URL.createObjectURL(v);
        }
        orig();
      };
    },
    counts: (v, ctx) => ({ source_seconds: ctx.sourceSeconds || 10 }),
  },
};

export const ORDER = ["presenter", "short", "image", "video", "voice", "swap"];
export const BLURBS = {
  presenter: ["Presenter", "You on camera, talking about any topic, in your own voice.", "from ~$1.70 / 30 s"],
  short: ["Short Maker", "An idea becomes a narrated, captioned vertical short.", "from ~$0.03"],
  image: ["Image", "Pictures from a sentence, edits and consistent characters.", "from ~$0.003"],
  video: ["Video", "Clips from text, or bring a still to life.", "from ~$0.02"],
  voice: ["Voiceover", "Narration in a stock voice or your cloned voice.", "from ~$0.002"],
  swap: ["Character Swap", "Your scene with a new character, original audio kept.", "from ~$0.20"],
};
