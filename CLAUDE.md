# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UMass AIEngine is a multi-stage chat facilitation AI system for the "Only-Human" chat application, specifically designed for Alzheimer's caregiver support groups on the FATHM platform. It determines when and how to inject facilitation messages into group conversations.

## Running the Pipeline

```bash
# Activate environment
source ~/.venvs/mass/bin/activate

# Run facilitation pipeline on a conversation file
python facilitate.py <conversation_file.json>

# With options
python facilitate.py conversation.json --model-path models/temporal_classifier.pkl --llm-model gpt-4o-mini --output results.json
```

**Prerequisites**: Python 3, openai, python-dotenv, joblib, numpy

**Environment**: Set `OPENAI_API_KEY` in `.env` file

## Architecture

The system implements a 3-stage decision pipeline with early termination:

```
Stage 1: Temporal Classification (Random Forest)
    ↓ (if facilitation indicated)
Stage 2: LLM Zero-Shot Verification (gpt-4o-mini)
    ↓ (if verified)
Stage 3: Generate Facilitation Message
```

**Stage 1** uses a pre-trained Random Forest classifier on temporal features:
- Message counts in 30min/1hr/3hr windows
- Average gap between last 5 messages
- Time since last message

**Stage 2** uses LLM to verify facilitation need based on conversation content, checking for staleness, conflict, distressed participants, topic dominance, or low engagement.

**Stage 3** generates an empathetic facilitation message using techniques like open-ended questions, emotional validation, and gentle redirection.

## Key Components

- `facilitate.py`: Main `FacilitationDecisionPipeline` class orchestrating all three stages
- `feature_extractor.py`: `TemporalFeatureExtractor` class for computing temporal features from conversation timestamps
- `models/temporal_classifier.pkl`: Pre-trained Random Forest model (loaded via joblib)

## Input Format

Conversation JSON must contain messages with `sender`, `time` (HH:MM format), and `content` fields:

```json
{
  "conversation": [
    {"sender": "Alice", "time": "14:30", "content": "Hello everyone"}
  ]
}
```

Also accepts `{"messages": [...]}` format.

## Development Notes

- No formal test framework; test by running pipeline on sample JSON files
- LLM stages use structured JSON responses with fallback handling
- Pipeline prints detailed logging to stdout showing each stage's decision
- Designed to run periodically (every 30 minutes per README workflow)
