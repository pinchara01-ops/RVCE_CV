"""Prompt construction for video moment search.

Kept in its own module because the prompt is the substance of this feature:
retrieval quality is decided almost entirely by how carefully the model is
asked to look. The sections below encode the failure modes that actually bite
in practice, each of which has cost us a wrong answer at least once:

- small or briefly visible targets being skipped in favour of the obvious
  subject of the shot;
- near-neighbour colours and similar objects being conflated (a peach bag
  beside pink shirts);
- blank, black, or corrupted stretches being described as if they held content;
- an audio track that contradicts the picture being allowed to invent visual
  events;
- absent audio or absent video being filled in from imagination;
- a confident answer being returned for a query with no true answer.
"""

from __future__ import annotations

SCANNING_DISCIPLINE = """\
HOW TO LOOK

Examine the footage exhaustively before answering. Most misses come from
skimming, so work through the whole file rather than settling on the first
plausible match.

- Sweep the entire frame, not just its subject. Check edges, corners,
  background, reflections, and anything held, worn, or carried.
- Small and briefly visible things count. A target on screen for well under a
  second, occupying a small part of the frame, is still a match. Do not
  overlook it because the shot is "about" something else.
- Partial visibility counts. Something half behind a person, cropped by the
  frame edge, out of focus, motion-blurred, or seen at an angle still matches
  if it is identifiable.
- Re-examine after a cut, a camera move, or a lighting change. The same object
  can look very different a moment later.
- If the target could plausibly appear more than once, keep scanning after the
  first hit. Report the distinct occurrences separately.
"""

DISCRIMINATION = """\
TELLING SIMILAR THINGS APART

The hard cases are near-misses, not absences. When the request names a
specific attribute, treat that attribute as the deciding test.

- Colour: distinguish neighbouring shades rather than collapsing them. Peach,
  salmon, coral, blush, rose, magenta, and hot pink are different colours. If
  the request says peach-pink, a saturated pink item is NOT a match, and the
  reverse also holds.
- Beware of colour bleed from surroundings, white balance, and coloured
  lighting. Judge the object's own colour, allowing for how the scene is lit.
- Distinguish the target from similar-looking neighbours. If the requested item
  sits among other items of a similar colour or shape, say which one is the
  target and what separates it: its form, material, size, or how it is being
  used. A bag is not a shirt even when both are pink.
- Objects vs. clothing vs. surfaces: match the kind of thing asked for, not
  just the colour or texture asked for.
- If two candidates both fit, return both and let the confidence scores
  express the difference.
"""

DEGRADED_FOOTAGE = """\
DAMAGED, BLANK, AND DISCONTINUOUS FOOTAGE

Real footage is not clean. Handle these without inventing content.

- Blank stretches: black, white, grey, frozen, transparent, colour-bar, static,
  or fully corrupted frames contain no evidence. Never describe them as
  containing anything. Do not treat a blank stretch as the start or end of a
  match.
- A blank or glitched stretch in the middle does NOT reset the clock.
  Timestamps stay measured from the start of the file, including through the
  gap.
- If a match is split by a blank stretch, either report the parts as separate
  sections or select the continuous portion that actually holds the evidence.
  Do not report a single range whose middle is blank.
- Encoding artefacts, heavy compression, dropped frames, or duplicated frames
  reduce confidence. They do not license a guess.
- Scenes that repeat, loop, or are near-identical: report the occurrence you
  can actually place in time, and do not merge separate occurrences into one
  range.
- Severe darkness, glare, or blur: if you cannot identify the target, say so
  through a low confidence or by omitting it. Do not upgrade a guess.
"""

CROSS_MODAL = """\
AUDIO AND PICTURE MAY NOT AGREE

Treat each channel as separate evidence. They are frequently mismatched, and
letting one speak for the other is the most common source of confident wrong
answers.

- The soundtrack may be unrelated to the picture: dubbed, replaced, stock
  music, a different event entirely, or a dog barking over footage containing
  no dog. When audio and picture disagree, the picture decides what is visible
  and the audio decides only what is audible.
- Never claim something is visible because you can hear it. If the request is
  about something visible, the answer must come from the frames.
- Equally, never claim a sound because you can see its likely source.
- If the request is about something audible, use the audio, and do not require
  the picture to corroborate it.
- If a section matches on one channel and is contradicted by the other, still
  report it, state plainly in the description which channel it matched on, and
  lower the confidence.

MISSING CHANNELS

- No audio track, or a silent track: report nothing about speech or sound.
  There is no transcript to quote and no audio events to list. Do not infer
  them from the picture. Judge the request on the picture alone.
- No video track, or an audio-only file: there is nothing to see. Do not
  describe visuals. Judge the request on the audio alone.
- Speech in any language counts, and it may switch mid-file. Do not ignore
  speech because it is not in the language of the request.
- If the request cannot be judged at all because the channel it depends on is
  absent, return no sections and explain that in the summary.
"""

GROUNDING = """\
GROUNDING

- Report only what the file actually contains. Never infer intent, identity,
  relationships, causes, or events occurring off-screen or outside the file.
- Do not use general knowledge about how such scenes usually unfold to fill in
  what you did not observe.
- Confidence must reflect the evidence: high only when the target is clearly
  identifiable, low when it is plausible but obscured, and omitted when it is a
  guess.
- Returning nothing is a correct answer. If the request has no true match,
  return an empty list and say so. Never promote the closest available thing to
  fill space.
"""


# Reused verbatim by the indexing prompt so both stages judge footage by the
# same standard: what one stage fails to record, the other can never retrieve.
SHARED_EDGE_CASES = "\n".join([DEGRADED_FOOTAGE, CROSS_MODAL, GROUNDING])


def build_search_prompt(
    *,
    query: str,
    spoken: bool,
    image_count: int,
    reference_clip: bool,
    max_moments: int,
) -> str:
    """Assemble the search prompt for whichever inputs were supplied."""

    lines: list[str] = [
        "You are a forensic video analyst locating the sections of a video that "
        "match a request. Accuracy matters more than speed: a missed detail is a "
        "failed search, and an invented one is worse.",
        "",
        "ATTACHED FILES, IN ORDER",
        "1. The video to search. Every timestamp you return refers to this file "
        "and to no other.",
    ]

    position = 2
    if spoken:
        lines.append(
            f"{position}. An audio recording of the user speaking their request. "
            "Listen to it and act on what was asked. Do not merely transcribe it. "
            "It may be in any language; understand it in the language spoken. "
            "This file is the request, not material to search."
        )
        position += 1
    for index in range(image_count):
        lines.append(
            f"{position}. Reference image {index + 1}: a person, object, or scene "
            "to find in the video. Match on the subject's own appearance: shape, "
            "colour, markings, clothing, and proportions. Ignore the reference "
            "image's background, lighting, and framing, which will not match the "
            "video. This file is part of the request, not material to search."
        )
        position += 1
    if reference_clip:
        lines.append(
            f"{position}. A reference clip showing the kind of moment to find. "
            "Match on the activity and the subjects it depicts, not on its "
            "specific location or timing. This file is part of the request, not "
            "material to search."
        )
        position += 1

    lines.append("")
    if query.strip():
        lines.append("THE REQUEST")
        lines.append(f'"{query.strip()}"')
        lines.append("")
    if spoken or image_count or reference_clip:
        lines.append(
            "The attachments above and any typed text form ONE request describing "
            "a single target. They are not separate searches. Where they overlap, "
            "they reinforce each other; where the text adds a qualifier the image "
            "cannot show (a colour, a time of day, an action), apply that "
            "qualifier as well."
        )
        lines.append("")

    lines.extend(
        [
            "Interpret the request generously in wording but strictly in "
            "substance: consider synonyms, related actions, and other ways of "
            "describing the same thing, while holding to every specific "
            "attribute the request names.",
            "",
            SCANNING_DISCIPLINE,
            DISCRIMINATION,
            DEGRADED_FOOTAGE,
            CROSS_MODAL,
            GROUNDING,
            "OUTPUT",
            "",
            "- start_seconds and end_seconds are measured from the start of the "
            "video being searched, in seconds.",
            "- Keep each section tight around the evidence: prefer 2-10 seconds. "
            "For a target visible only briefly, return a short window centred on "
            "it rather than padding it out.",
            f"- Return up to {max_moments} sections, ordered by confidence, "
            "highest first. Cover genuinely distinct parts of the video rather "
            "than several overlapping ranges around one event.",
            f"- If fewer than {max_moments} sections genuinely match, return only "
            "those that do. Do not pad the list.",
            "- description: one specific sentence naming what is visible and "
            "where in the frame, and what distinguishes it from similar things "
            "nearby. Write what you saw, not what the request asked for.",
            "- confidence: 0.0-1.0, honestly reflecting how certain the "
            "identification is.",
            "- summary: one sentence restating what was asked for and what you "
            "found, including saying plainly when you found nothing.",
        ]
    )
    return "\n".join(lines)
