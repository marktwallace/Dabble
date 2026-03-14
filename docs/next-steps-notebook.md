# /notebook — Next Steps

## Concept

A new output command alongside `/snapshot` and `/report`, generating a **Marimo** reactive notebook from the conversation.

Marimo notebooks are plain `.py` files (not `.ipynb`), stored as functions in a DAG — change one cell, downstream cells update automatically. This fits the project's text-file principle and produces something the analyst can open in an IDE, extend with new cells, and iterate on outside of list-pet.

## Audience differentiation

The existing outputs split by audience:
- `/snapshot` → colleagues (static, presentable)
- `/report` → colleagues (live, parameterized Streamlit app)
- `/notebook` → the analyst (reactive, editable, extensible)

This is a different value proposition from `/report`, not a duplicate.

## What makes it appealing

- Reactive model: change a date slider → SQL re-runs → chart updates automatically
- Transferable: the analyst owns an artifact they can extend without list-pet
- Plain `.py` file: consistent with the project's everything-is-text-files principle
- Can be served as an app or used as a notebook (both modes)

## The open question

The generation prompt needs to teach Claude Marimo's cell model: cells are functions, no global mutable state between cells, UI elements are reactive values. This is more complex than the Streamlit template Claude already generates well. The risk is subtly broken notebooks that look correct but have hidden reactivity bugs.

## How to validate before building

Feed a real conversation transcript to Claude with a Marimo-generation prompt and inspect whether the output is correct. The `/report` generation architecture (full conversation to LLM, thin Python wrapper) would apply here too — the question is purely whether Claude can generate a structurally correct Marimo notebook reliably.

If it can: implementation is straightforward. If the output is subtly wrong: that's the blocker to address first.

## Dependencies

Add `marimo` to `requirements.txt`. No other structural changes needed.
