---
name: meme-generation
description: Generate meme ideas from a topic by selecting a suitable meme template and producing funny, relatable captions.
version: 1.0.0
author: adanaleycio
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [creative, memes, humor, social-media]
    related_skills: [ascii-art]
    requires_toolsets: [terminal]
---

# Meme Generation

Generate meme concepts from a topic by choosing a fitting meme template and writing short, funny captions.

## When to Use

Use this skill when the user:
- wants to make a meme about a topic
- has a subject, situation, or frustration and wants a funny meme version
- asks for a relatable, sarcastic, or programmer-style meme idea
- wants caption ideas matched to a known meme format

Do not use this skill when:
- the user wants a full graphic editor workflow
- the request is for hateful, abusive, or targeted harassment content
- the user wants a random joke without meme structure

## Quick Reference

| Input | Meaning |
|---|---|
| topic | The main subject of the meme |
| tone | Optional style: relatable, programmer, sarcastic |
| language | Optional output language |

| Template | Best for |
|---|---|
| This is Fine | chaos, denial, pretending things are okay |
| Distracted Boyfriend | distraction, shifting priorities |
| Two Buttons | dilemma between two bad choices |
| Expanding Brain | escalating irony or absurd superiority |
| Drake Hotline Bling | rejecting one thing and approving another |
| Gru's Plan | a plan that fails midway |
| Woman Yelling at Cat | blame, misunderstanding, argument |
| Change My Mind | strong ironic opinion |

## Procedure

1. Read the user's topic and identify the core situation.
2. Map the topic to the clearest meme pattern:
   - chaos -> This is Fine
   - distraction -> Distracted Boyfriend
   - dilemma -> Two Buttons
   - escalation -> Expanding Brain
   - rejection/preference -> Drake Hotline Bling
   - failed plan -> Gru's Plan
   - blame/argument -> Woman Yelling at Cat
   - strong ironic opinion -> Change My Mind
3. Choose the simplest fitting template instead of overthinking edge cases.
4. Briefly explain why the template fits in 1 short sentence.
5. Generate 3 caption options only.
6. Keep each caption short, ideally one line per field and no more than 8–12 words.
7. Keep captions aligned with the structure of the chosen meme.
8. Only use tone, language, or template overrides if the user explicitly provides them.
9. If the user requests programmer humor, prefer themes like debugging, deployments, meetings, deadlines, code review, technical debt, and production incidents.
10. If the user requests Turkish, write naturally in Turkish instead of translating word-for-word.

## Pitfalls

- Do not choose templates randomly; follow the pattern mapping first.
- Do not over-explain the joke or the template choice.
- Do not make captions too long.
- Do not ignore explicit tone, language, or template requests.
- Do not generate hateful, abusive, or personally targeted content.
- Do not force a meme format if the topic does not fit clearly.

## Verification
The output is correct if:
- the chosen template clearly matches the topic structure
- the explanation is one short, sensible sentence
- all 3 captions are short, readable, and meme-like
- the tone matches the user's request when specified
- the result is usable as a meme draft without major rewriting
