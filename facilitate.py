import json
import os
from typing import List, Dict, Any, Optional
from openai import OpenAI
from dotenv import load_dotenv
import joblib
import numpy as np
from feature_extractor import TemporalFeatureExtractor

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class FacilitationDecisionPipeline:
    """Multi-stage decision pipeline for chat facilitation."""

    def __init__(
        self,
        model_path: str = 'models/rf_classifier.pkl',
        llm_model: str = "gpt-4o-mini"
    ):
        """
        Initialize the facilitation pipeline.

        Args:
            model_path: Path to trained Random Forest classifier
            llm_model: OpenAI model to use for LLM stages
        """
        self.llm_model = llm_model
        self.client = client

        # Load the trained Random Forest model
        print(f"Loading trained model from {model_path}...")
        model_data = joblib.load(model_path)
        self.rf_model = model_data['model']
        self.feature_names = model_data['feature_names']
        print(f"Model loaded successfully with {len(self.feature_names)} features")

    def _extract_features_vector(self, features: Dict[str, Any]) -> np.ndarray:
        """
        Convert features dictionary to numpy array in correct order.

        Args:
            features: Dictionary of temporal features

        Returns:
            Feature vector as numpy array
        """
        feature_vector = [
            features['messages_last_30min'],
            features['messages_last_hour'],
            features['messages_last_3hours'],
            # features['messages_today'],
            features['avg_gap_last_5_messages_min'],
            # features['avg_gap_last_10_messages_min'],
            # features['unique_participants_last_5'],
            # features['unique_participants_last_10'],
            # features['conversation_duration_hours'],
            features['time_since_last_message_min'],
            # features['total_messages'],
            # features['current_message_index']
        ]
        return np.array([feature_vector])

    def stage1_temporal_classification(
        self,
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Stage 1: Extract temporal features and use Random Forest to classify.

        Args:
            messages: List of message dicts with 'sender', 'time', 'content'

        Returns:
            Dict with 'should_facilitate' (bool), 'probability', 'features'
        """
        print("\n" + "="*60)
        print("STAGE 1: Temporal Feature Classification")
        print("="*60)

        # Extract features from the conversation
        current_index = len(messages) - 1
        extractor = TemporalFeatureExtractor(messages, current_index)
        features = extractor.extract_all_features()

        print(f"\nExtracted features:")
        for key, value in features.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.2f}")
            else:
                print(f"  {key}: {value}")

        # Convert to feature vector
        X = self._extract_features_vector(features)

        # Get prediction and probability
        prediction = self.rf_model.predict(X)[0]
        probabilities = self.rf_model.predict_proba(X)[0]
        facilitation_probability = probabilities[1]  # Probability of class 1

        print(f"\nRandom Forest Decision:")
        print(f"  Prediction: {'FACILITATE' if prediction == 1 else 'NO FACILITATION'}")
        print(f"  Confidence: {facilitation_probability:.2%}")

        return {
            'should_facilitate': bool(prediction == 1),
            'probability': float(facilitation_probability),
            'features': features
        }

    def stage2_llm_verification(
        self,
        messages: List[Dict[str, Any]],
        last_n: int = 10
    ) -> Dict[str, Any]:
        """
        Stage 2: Use LLM to verify if facilitation is needed (zero-shot).

        Args:
            messages: List of message dicts
            last_n: Number of recent messages to send to LLM

        Returns:
            Dict with 'needs_facilitation' (bool), 'reasoning', 'confidence'
        """
        print("\n" + "="*60)
        print("STAGE 2: LLM Zero-Shot Verification")
        print("="*60)

        # Get last N messages
        recent_messages = messages[-last_n:] if len(messages) > last_n else messages

        # Format messages for LLM
        conversation_text = ""
        for msg in recent_messages:
            conversation_text += f"[{msg['time']}] {msg['sender']}: {msg['content']}\n"

        prompt = f"""You are a professional facilitator for an online support group for Alzheimer's caregivers on the FATHM platform.

Your task is to analyze the following recent conversation and determine if facilitator intervention is needed RIGHT NOW.

CONVERSATION (last {len(recent_messages)} messages):
{conversation_text}

FACILITATION IS NEEDED when:
- Conversation has died out or stalled (long silence, disengagement)
- Conflict or tension between participants that needs de-escalation
- Someone appears distressed or needs emotional support but isn't getting it
- Conversation is dominated by 1-2 people, excluding others
- Topic has become unproductive or gone off track
- Someone asks a question that goes unanswered
- Negative or harmful content that needs addressing
- Group energy is very low and needs a boost

NO FACILITATION NEEDED when:
- Conversation is flowing naturally and productively
- Multiple people are engaged and participating
- Emotional support is being provided peer-to-peer
- Discussion is on-topic and helpful
- Natural pauses in conversation (not concerning silence)
- Recent facilitation already occurred (avoid over-facilitating)

Based on the conversation above, does this moment require facilitator intervention?

Respond in JSON format with:
{{
    "needs_facilitation": true or false,
    "reasoning": "Brief explanation of your decision",
    "confidence": 0.0 to 1.0
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert online support group facilitator. Respond only with valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            print(f"\nLLM Verification Result:")
            print(f"  Needs Facilitation: {result['needs_facilitation']}")
            print(f"  Reasoning: {result['reasoning']}")
            print(f"  Confidence: {result['confidence']:.2%}")

            return result

        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return {
                "needs_facilitation": False,
                "reasoning": f"Error during verification: {str(e)}",
                "confidence": 0.0
            }

    def stage3_generate_facilitation(
        self,
        messages: List[Dict[str, Any]],
        verification_reasoning: str,
        last_n: int = 10
    ) -> Dict[str, Any]:
        """
        Stage 3: Generate facilitation response using LLM.

        Args:
            messages: List of message dicts
            verification_reasoning: Reasoning from stage 2
            last_n: Number of recent messages to use for context

        Returns:
            Dict with 'facilitation_message' and 'approach'
        """
        print("\n" + "="*60)
        print("STAGE 3: Generate Facilitation Response")
        print("="*60)

        # Get last N messages
        recent_messages = messages[-last_n:] if len(messages) > last_n else messages

        # Format messages for LLM
        conversation_text = ""
        for msg in recent_messages:
            conversation_text += f"[{msg['time']}] {msg['sender']}: {msg['content']}\n"

        prompt = f"""You are a professional facilitator for an online support group for Alzheimer's caregivers on the FATHM platform.

Based on your analysis, you determined that facilitation is needed for the following reason:
{verification_reasoning}

RECENT CONVERSATION:
{conversation_text}

Generate an appropriate facilitation message that:
1. Addresses the specific need identified (e.g., re-engaging participants, supporting someone, redirecting conversation)
2. Is warm, empathetic, and supportive in tone
3. Is brief and natural (1-3 sentences typically)
4. Encourages healthy group interaction
5. Uses appropriate facilitation techniques:
   - Open-ended questions to spark discussion
   - Validation and acknowledgment of feelings
   - Gentle redirection if needed
   - Invitation for quieter members to share
   - Summarizing and bridging between topics
   - Providing resources or information when helpful

Respond in JSON format with:
{{
    "facilitation_message": "The message to send to the group",
    "approach": "Brief description of the facilitation technique used (e.g., 'Open-ended question', 'Emotional validation', 'Re-engagement prompt')"
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert online support group facilitator specializing in caregiver support. Respond only with valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,  # Higher temperature for more natural, varied responses
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            print(f"\nGenerated Facilitation:")
            print(f"  Approach: {result['approach']}")
            print(f"  Message: {result['facilitation_message']}")

            return result

        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return {
                "facilitation_message": "I'm here to support the group. How is everyone doing?",
                "approach": f"Error - fallback message (error: {str(e)})"
            }

    def run_pipeline(
        self,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Run the complete multi-stage facilitation pipeline.

        Args:
            messages: List of message dicts with 'sender', 'time', 'content'

        Returns:
            Dict with complete pipeline results and final decision
        """
        print("\n" + "="*70)
        print("FACILITATION DECISION PIPELINE")
        print("="*70)
        print(f"Analyzing conversation with {len(messages)} messages...")

        pipeline_result = {
            'stage1': None,
            'stage2': None,
            'stage3': None,
            'final_decision': 'NO_FACILITATION',
            'facilitation_message': None
        }

        # STAGE 1: Temporal Classification
        stage1_result = self.stage1_temporal_classification(messages)
        pipeline_result['stage1'] = stage1_result

        if not stage1_result['should_facilitate']:
            print("\n" + "="*70)
            print("FINAL DECISION: NO FACILITATION NEEDED")
            print("="*70)
            print("Random Forest determined facilitation is not needed.")
            return pipeline_result

        # STAGE 2: LLM Verification
        stage2_result = self.stage2_llm_verification(messages)
        pipeline_result['stage2'] = stage2_result

        if not stage2_result['needs_facilitation']:
            print("\n" + "="*70)
            print("FINAL DECISION: NO FACILITATION NEEDED")
            print("="*70)
            print("LLM verification determined facilitation is not needed.")
            print(f"Reasoning: {stage2_result['reasoning']}")
            pipeline_result['final_decision'] = 'NO_FACILITATION_AFTER_VERIFICATION'
            return pipeline_result

        # STAGE 3: Generate Facilitation
        stage3_result = self.stage3_generate_facilitation(
            messages,
            stage2_result['reasoning']
        )
        pipeline_result['stage3'] = stage3_result
        pipeline_result['final_decision'] = 'FACILITATE'
        pipeline_result['facilitation_message'] = stage3_result['facilitation_message']

        print("\n" + "="*70)
        print("FINAL DECISION: FACILITATION NEEDED")
        print("="*70)
        print(f"Facilitation Message:")
        print(f"  {stage3_result['facilitation_message']}")
        print("="*70)

        return pipeline_result


def main():
    """Example usage of the facilitation pipeline."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Run facilitation decision pipeline on a conversation'
    )
    parser.add_argument(
        'conversation_file',
        type=str,
        help='Path to JSON file containing conversation'
    )
    parser.add_argument(
        '--model-path',
        type=str,
        default='models/rf_classifier.pkl',
        help='Path to trained Random Forest model (default: models/rf_classifier.pkl)'
    )
    parser.add_argument(
        '--llm-model',
        type=str,
        default='gpt-4o-mini',
        help='OpenAI model to use (default: gpt-4o-mini)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Optional: Save pipeline results to JSON file'
    )

    args = parser.parse_args()

    # Load conversation
    with open(args.conversation_file, 'r') as f:
        data = json.load(f)

    messages = data.get('conversation', data.get('messages', []))

    if not messages:
        print("Error: No messages found in conversation file")
        return

    # Initialize pipeline
    pipeline = FacilitationDecisionPipeline(
        model_path=args.model_path,
        llm_model=args.llm_model
    )

    # Run pipeline
    result = pipeline.run_pipeline(messages)

    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
