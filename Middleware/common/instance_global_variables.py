# Middleware/common/instance_global_variables

import uuid

INSTANCE_ID = str(uuid.uuid4())
CONFIG_DIRECTORY = None
USER = None
LOGGING_DIRECTORY = "logs"
API_TYPE = "openai"
IMAGE_API_TYPES = ["ollamaApiChatImageSpecific", "openAIApiChatImageSpecific"]

# Workflow override extracted from the model field in API requests.
# When set, this workflow is used instead of normal routing.
# Format: just the workflow name (e.g., "Coding_Workflow")
WORKFLOW_OVERRIDE = None
