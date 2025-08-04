# middleware/llmapis/handlers/impl/koboldcpp_api_image_specific_handler.py
from typing import List, Optional, Dict

from Middleware.llmapis.handlers.impl.koboldcpp_api_handler import KoboldCppApiHandler


class KoboldCppImageSpecificApiHandler(KoboldCppApiHandler):
    """
    Handles interactions with KoboldCpp when image data is included in the request.

    This class extends `KoboldCppApiHandler` to add support for multimodal inputs.
    It intercepts the conversation to extract any image data sent by the client,
    injects it into the generation parameters, and then relies on the parent
    handler's logic to construct the final payload for the KoboldCpp API.
    """

    def _prepare_payload(self, conversation: Optional[List[Dict[str, str]]], system_prompt: Optional[str],
                         prompt: Optional[str]) -> Dict:
        """
        Prepares the payload by adding image data before calling the parent implementation.

        This method overrides the standard payload preparation to handle multimodal
        inputs. It inspects the `conversation` for any messages with the role "images".
        If found, it extracts their content and adds it to the `gen_input`
        dictionary. It then calls the parent class's `_prepare_payload` method to
        construct the text prompt and assemble the rest of the request payload.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The history of the conversation,
                which may include special "images" role messages.
            system_prompt (Optional[str]): The system-level instruction for the LLM.
            prompt (Optional[str]): The latest user text prompt.

        Returns:
            Dict: The final JSON payload, including image data if present, ready to be
            sent to the API.
        """
        if conversation:
            image_contents = [msg["content"] for msg in conversation if msg.get("role") == "images"]
            if image_contents:
                self.gen_input["images"] = image_contents

        return super()._prepare_payload(conversation, system_prompt, prompt)