# IBVAP — Official 3-Minute Video Pitch Script & Performer Action Plan

**Competition Standards Met:** 100% Compliant with Sections (a) through (e)  
**Total Target Duration:** 2:45 to 2:55 (Never exceeds the strict 3:00 minute limit)  
**Recording Mode:** Single Continuous Screen Recording (OBS / Loom / Windows Game Bar `Win + G`)  
**Resolution:** 1920 × 1080 (16:9 Landscape)  
**Target Video File Name:** `[YourProblemStatementID]_IBVAP_Video.mp4`

---

## 1. Quick Master Timing & Evaluation Checklist

This table maps directly to the official judging rubric:

| Time | Rubric Section | What You Show On-Screen | What You Say (Word-for-Word) |
|---|---|---|---|
| **0:00 – 0:30** (30s) | **(a) Problem Statement & Societal Need** | Title Card / Overview (or Cockpit HUD view) | Explain the national security problem: passive border CCTV & human sentry fatigue. |
| **0:30 – 0:55** (25s) | **(b) Target Audience & Stakeholders** | Stakeholder Card / Top Cockpit Banner | Identify beneficiaries: BSF, ITBP, SSB, Control Room sentries, and MHA leadership. |
| **0:55 – 1:55** (60s) | **(c) Proposed Solution & Prototype Demo** | **Live Browser at `http://localhost:8000`:**<br>1. Ingest clip at `/use/footage`<br>2. Automatic AI detection & tracking<br>3. Virtual fence tripwire intrusion<br>4. Incident logged in alert rail | **Complete Input-to-Output Use Case:** Demonstrate working AI converting standard footage into actionable perimeter security. |
| **1:55 – 2:25** (30s) | **(d) Innovation & Technical Approach** | Architecture Diagram & Code Locations | Explain DirectML GPU edge acceleration, Cross-Class NMS, and **clearly distinguish Implemented vs. Future features**. |
| **2:25 – 2:55** (30s) | **(e) Feasibility, Scalability & Close** | Offline Edge Architecture & Closing Card | Highlight low-cost BOP deployment, 100% offline edge autonomy, and concluding value proposition. |

---

## 2. Performer Action Plan & Word-for-Word Narration

> [!TIP]
> **How to Record This Easily in 15 Minutes:**
> You can record this in **one continuous take**! Open your browser in full screen (`F11`). Start on your Title/Overview tab, switch to `http://localhost:8000/use/footage` for the demo, then show the architecture summary at the end.

---

### Segment A: Problem Statement & Societal Need (0:00 – 0:30)
* **Time:** 0:00 to 0:30 (30 Seconds | 68 Words)
* **Goal:** Hook the judges immediately. Explain the societal need and security gap without lengthy intros or fluff.

#### [YOUR ON-SCREEN ACTION]:
* Start recording with your browser or presentation slide showing:  
  **"IBVAP: Intelligent Border Video Analytics Platform"**  
  *Problem Statement Focus:* Thousands of passive CCTV cameras along border outposts requiring continuous human monitoring.

#### [WHAT YOU SAY OUT LOUD (READ VERBATIM)]:
> *"Across thousands of kilometers of international borders, security forces deploy CCTV cameras at Border Out Posts, checkposts, and transit corridors.*
> 
> *However, conventional CCTV systems are strictly passive—recording video that is only reviewed after an infiltration or security breach has already occurred.*
> 
> *Continuous human monitoring leads to rapid operator fatigue within twenty minutes, creating dangerous operational blind spots. Meanwhile, replacing these cameras with specialized smart-camera hardware is cost-prohibitive, fragile, and difficult to maintain in remote border outposts.*
> 
> *Our borders need automated, software-defined intelligence that works on existing infrastructure."*

---

### Segment B: Target Audience, Beneficiaries & Stakeholders (0:30 – 0:55)
* **Time:** 0:30 to 0:55 (25 Seconds | 56 Words)
* **Goal:** Name the exact defense stakeholders and explain how IBVAP benefits both frontline sentries and commanders.

#### [YOUR ON-SCREEN ACTION]:
* Show a clean graphic or text overlay listing the 3 stakeholder tiers:
  * **Frontline Beneficiaries:** BSF (Border Security Force), ITBP, and SSB sentries at remote BOPs.
  * **Operational Stakeholders:** Sector Control Room Operators & Quick Reaction Teams.
  * **Strategic Leadership:** Ministry of Home Affairs (MHA) & National Border Management.

#### [WHAT YOU SAY OUT LOUD (READ VERBATIM)]:
> *"IBVAP is designed directly for frontline border guarding forces: the BSF, ITBP, and SSB.*
> 
> *For the sentry stationed at an isolated Border Out Post, IBVAP acts as an automated 24/7 co-pilot, generating immediate audio-visual alerts the moment a perimeter breach occurs.*
> 
> *For Control Room Operators and Quick Reaction Teams, it replaces hours of raw video feeds with high-priority, deduplicated operational incidents.*
> 
> *And for defense leadership, it transforms legacy cameras into an intelligent surveillance network without requiring expensive hardware replacements."*

---

### Segment C: Working Prototype Demo — Complete Input-to-Output Use Case (0:55 – 1:55)
* **Time:** 0:55 to 1:55 (60 Seconds | 134 Words)
* **Goal:** **This is the core evaluation minute.** Show the working software from input (video upload) to processing (AI detection) to output (incident alert).

#### [YOUR ON-SCREEN ACTION (STEP-BY-STEP CLICKTHROUGH)]:
1. **[0:55] INPUT:**  
   * Navigate your browser to: `http://localhost:8000/use/footage`  
   * The page shows: *"Use video footage — Upload a local MP4 clip and analyze it as a camera source."*  
   * Click **Browse**, select `tests/fixtures/test-footage.mp4` (or any surveillance MP4 clip in your project folder), and click **"Use footage"**.
2. **[1:08] PROCESSING:**  
   * The app automatically validates the footage and redirects directly to the **Cockpit** (`http://localhost:8000`).
   * The video footage begins playing on the screen.
   * Point cursor to the top-left HUD badge: `[DIRECTML]`. Note that ONNX AI models are running locally on GPU at edge speed.
   * Point cursor to the high-contrast bounding boxes: `Person #1 90%` and `Face 91%`.
   * Point cursor to the top-right counter: `● 1 Target` — highlight that discrete subjects are counted accurately without double-counting faces.
3. **[1:25] DETECTION RULE (VIRTUAL FENCE):**  
   * Point cursor to the green perimeter line labeled `RESTRICTED ZONE ACTIVE`.
   * As the target's ground-contact footpoint enters the polygon, watch the detection trigger.
4. **[1:40] OUTPUT (INCIDENT LOGGED):**  
   * The bottom **Security Incidents & Alerts** rail immediately captures the event:  
     `ZONE INTRUSION` • `Zone: zone-restricted-1` • `92% conf`.
   * Click the **`Contract ▲`** button: show the drawer fold into a compact single-line bar to prove operator flexibility. Click **`Expand ▼`** to show the audit trail.

#### [WHAT YOU SAY OUT LOUD (READ VERBATIM)]:
> *"Here is the working prototype of IBVAP demonstrating a complete, end-to-end operational use case.*
> 
> *We begin with input ingestion: using our footage processing module, we select a surveillance video clip and promote it into an active monitoring channel. No smart camera hardware is required.*
> 
> *Once ingested, our DirectML acceleration engine processes frames in just eighteen milliseconds on commodity hardware.*
> 
> *Notice our tactical HUD: using dual-stroke high-contrast outlines, targets are tracked with razor-sharp clarity across complex backgrounds. Discrete targets are counted accurately without double-counting faces.*
> 
> *Now, observe the perimeter tripwire. The moment the target's footpoint crosses into the virtual restricted zone, IBVAP instantly triggers a high-urgency intrusion alert.*
> 
> *Our state-transition engine logs the breach once, tracks dwell, and maintains a complete audit trail without alert spam. The operator can collapse the alert rail with a single click to maintain unobstructed view."*

---

### Segment D: Innovation, Technical Approach & Advantages (1:55 – 2:25)
* **Time:** 1:55 to 2:25 (30 Seconds | 74 Words)
* **Goal:** Present the technical differentiators and **clearly distinguish implemented features from future roadmap** (mandatory evaluation standard).

#### [YOUR ON-SCREEN ACTION]:
* Show a clean slide or screen section with the Architecture & Implementation Status table:

```
+-----------------------------------------------------------------------------------+
| PIPELINE ARCHITECTURE & CODE IMPLEMENTATION STATUS                                |
+-----------------------------------------------------------------------------------+
| [1] Ingestion:       PyAV Async Demuxer         -> src/ibvap/api/routes/cameras.py |
| [2] Edge Inference:  DirectML / ONNX YOLO (18ms)-> src/ibvap/core/detector.py     |
| [3] Deduplication:   Cross-Class Spatial NMS    -> src/ibvap/core/tracker.py      |
| [4] Zone Engine:     Ray-Casting Footpoint      -> src/ibvap/core/zone_engine.py  |
| [5] Outbox Engine:   State-Transition Gating    -> src/ibvap/events/outbox.py     |
+-----------------------------------------------------------------------------------+
| ✔ IMPLEMENTED TODAY: Video/RTSP Ingestion, DirectML Edge AI, Virtual Fence Alarms |
| ➔ FUTURE ROADMAP:    Thermal IR Sensor Fusion, Autonomous PTZ Camera Handoff      |
+-----------------------------------------------------------------------------------+
```

#### [WHAT YOU SAY OUT LOUD (READ VERBATIM)]:
> *"IBVAP's core innovation is hardware independence and explainable spatial logic.*
> 
> *Our architecture combines an asynchronous PyAV demuxer with DirectML acceleration, executing ONNX models on commodity GPUs without vendor lock-in. To eliminate false alarms, our custom tracker applies cross-class spatial deduplication, preventing vehicles or persons from generating duplicate ghost boxes in busy scenes.*
> 
> *Crucially, our video ingestion, edge tracking, and virtual fence intrusion engines are fully implemented and functional today. Our future roadmap expands this foundation to multi-camera PTZ handoffs and long-range thermal infrared sensor fusion."*

---

### Segment E: Feasibility, Scalability & Concluding Impact (2:25 – 2:55)
* **Time:** 2:25 to 2:55 (30 Seconds | 68 Words)
* **Goal:** Reassure judges on real-world feasibility, low bandwidth tolerance, and finish with a strong, memorable closing punchline.

#### [YOUR ON-SCREEN ACTION]:
* Show the closing slide:
  * **IBVAP — Intelligent Border Video Analytics Platform**
  * *Deployment Model:* Autonomous Edge Nodes at Remote BOPs • Lightweight Tactical Telemetry
  * *Key Takeaway:* Software-Defined Border Intelligence. Any Camera. Any Terrain. Real Time.
  * Your Team Name, Problem Statement ID, and Date.

#### [WHAT YOU SAY OUT LOUD (READ VERBATIM)]:
> *"IBVAP is designed for immediate operational feasibility. Each Border Out Post can deploy on an inexpensive edge computer, functioning with one hundred percent autonomy even during complete satellite or internet communication blackouts.*
> 
> *When connectivity is available, lightweight incident telemetry relays seamlessly into existing Command and Control centers.*
> 
> *By transforming existing CCTV infrastructure into intelligent autonomous sentries, IBVAP protects our borders and gives our security forces actionable, real-time awareness.*
> 
> *Intelligent Border Video Analytics Platform—turning passive surveillance into proactive border defense."*

---

## 3. Pre-Recording Checklist (Read Before Hitting Record)

- [ ] **Timing Guard:** Rehearse once with a stopwatch. Keep each section within its allocated seconds (total ~2:50).
- [ ] **No Credentials on Screen:** Ensure no API keys, tokens, or personal passwords appear in your browser or slides.
- [ ] **Screen Resolution:** Set monitor / recording capture to `1920 × 1080` (16:9 Landscape).
- [ ] **Browser Prepared:** Have `http://localhost:8000` already open and working before starting your recording.
- [ ] **Export Naming:** Export as MP4 and name the file:  
  `[YourProblemStatementID]_IBVAP_Video.mp4`
