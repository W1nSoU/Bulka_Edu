# B2B Cold Email Campaign: Bulka Telegram Automation

## Overview
Rewrite two B2B cold email templates for the Bulka Telegram platforms (Onboarding and Shift-sharing) using marketing best practices, humanizer guidelines, and parallel agent execution. The goal is to increase the reply rate and drive interest in seeing a demo bot or discussing a custom solution.

## Architecture & Components

### 1. Email 1: Onboarding & Training Bot
- **Audience:** HR Directors, Head of Training, Operations Managers in retail networks.
- **Core Value:** Automates first 3 days of training; saves 75% of managers' time on manual checking.
- **Goal:** Get a reply requesting the demo bot link.

### 2. Email 2: Shift-sharing Bot
- **Audience:** Regional Managers, Operations Directors in retail networks.
- **Core Value:** Closes sudden shift gaps in 12 minutes without manual calling.
- **Goal:** Get a reply requesting the demo bot link.

## Strategy
- **Approach:** "Interest-Based CTA". We will not include a direct link to the demo bot or GitHub in the initial email.
- **Custom Solution Angle:** Explicitly state that we build *custom* solutions adapted to their specific network processes, not just selling an off-the-shelf SaaS tool.
- **CTA:** Soft, low-friction question asking if they want the link to a demo bot to click around themselves. Example: "Я зібрав короткого демо-бота, де можна подивитись це зсередини. Скинути вам лінк?"

## Tone & Voice (Humanizer)
- Strip all "AI vocabulary" (e.g. інноваційний, забезпечить, унікальний, ефективно).
- Strip overly formal sales openings ("Hello, my name is X and I do Y"). Start immediately with an observation about their world.
- Use short, punchy sentences and a peer-to-peer tone.
- Avoid multiple CTAs or complex requests.

## Execution Plan
We will use **Parallel Dispatch** for the execution:
- **Agent 1:** Dedicated to writing the Onboarding email using `cold-email` and `humanizer` constraints.
- **Agent 2:** Dedicated to writing the Shift-sharing email using `cold-email` and `humanizer` constraints.
- Both agents will work concurrently to avoid context bleeding and ensure maximum focus on their specific persona.
