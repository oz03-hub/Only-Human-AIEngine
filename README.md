This is the UMass AIEnginge for the Only-Human chat application.

It serves the logic for the AI facilitation BOT.

# Proposed Workflow
## Pre-requisites

1. The AI facilitator will be added to every chatroom as another participant.
2. The AIEngine will use provided chat API endpoints to read incoming new messages.
3. The AIEngine will use provided chat API endpoints to post a message.
4. The AIEngine will be given a pre-trained Random Forest Model to compute the first decision step.

## Workflow for facilitation
1. As the first stage, we will run the Random Forest model to determine if facilitation is needed based on temporal features.
    1. To extract temporal features, we will use feature_extractor.py
    2. Model is saved in `models/temporal_classifier.pkl`.
2. If the first stage determines the chat needs facilitation, we will move on to the second stage.
3. As the second stage, we will make an API request to OpenAI to provide the recent conversation to ask it again if it needs facilitation.
4. If the second stage replies it needs facilitation, we will move on to the third stage.
5. As the third stage, we will use the recent messages in the chat to craft the facilitation message.


## MVP Notes
1. We can run the workflow every 30 minutes on each active chatroom to determine if it needs facilitation.
2. For database, we will probably need a relational database, unless there is a no-sql version that we can develop with easily.
3. Example projected API schemas.
```
// Forward new messages to UMass AI
async function onNewMessage(groupId, message) {
  await umasAIClient.send({
    groupId: groupId,
    userId: message.userId,
    content: message.content,
    timestamp: message.createdAt,
    context: await getGroupConversationHistory(groupId)
  });
}

// Receive and display AI responses
async function onAIResponse(groupId, aiResponse) {
  await db.insert(chatMessages).values({
    channelId: groupId,
    userId: AI_PARTICIPANT.id,
    userName: AI_PARTICIPANT.name,
    content: aiResponse.message,
    isAI: true
  });
}
```
The chat app will use these functions to send the AIEngine data.

4. Right now, we don't have all the details about schemas, APIs from the chat application, so for now, let's focus on laying out the core API.
5. A simple version of the entire pipeline can be found at 
