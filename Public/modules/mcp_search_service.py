import os
import json
import logging
import time
from typing import Dict, Any, List
import requests
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Search MCP Service", description="MCP service for code search")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchParams(BaseModel):
    query: str
    projects: str = None
    max_results: int = 10

@app.get("/openapi.json", tags=["OpenAPI"])
async def get_openapi():
    return app.openapi()

@app.post("/search", 
          tags=["Search"], 
          summary="Search code repositories",
          description="Search code repositories using a query and optionally filter by projects",
          operation_id="tool_endpoint_search_search_post")
async def search(params: SearchParams):
    try:
        # Extract parameters
        query = params.query
        projects = params.projects
        max_results = params.max_results
        
        # Format the directories list from comma-separated project names
        project_names = [name.strip() for name in projects.split(',')]
        directories = [f"../{''.join(name)}" for name in project_names]
        
        # Prepare the request payload
        payload = {
            "working_dir": "/workspace/projects/empty/",
            "directories": directories,
            "prompt": query,
            "ignores": [
                "**/docker/**", "**/.git/**", "**/.vscode/**", "**/node_modules/**", 
                "**/build/**", "**/.idea/**", "**/__pycache__/**", "**/dist/**", 
                "**/resources/swagger/**", "**/gradleBuild/**", "**/*.xcframework/**", 
                "**/target/**", "**/bin/**", "**/obj/**", "**/out/**", "**/vendor/**", 
                "**/*.min.js", "**/*.min.css", "**/.vs/**", "**/.settings/**", 
                "**/*.pyc", "**/.venv/**", "**/.env/**", "**/venv/**", "**/*.class", 
                "**/.mvn/**", "**/npm-debug.log*", "**/.npm/**", "**/*.xcodeproj/**", 
                "**/*.xcworkspace/**", "**/Pods/**", "**/logs/**", "**/*.log", 
                "**/cache/**", "**/.docker/**"
            ],
            "additional_params": {
                "OPENAI_API_BASE": "http://192.168.0.20:8080/v1",
                "OPENAI_API_KEY": "empty",  
                "DIR_ASSISTANT__LITELLM_API_KEYS__OPENAI_API_KEY": "empty",
                "lm_studio_api_key": "empty",
                "DIR_ASSISTANT__LITELLM_MODEL": "openai/glm-4-9b",
                "LITELLM_MODEL": "openai/glm-4-9b",
                "DIR_ASSISTANT__LITELLM_EMBED_MODEL": "openai/bge-m3",
                "LITELLM_EMBED_MODEL": "openai/bge-m3",
                "DIR_ASSISTANT__LITELLM_CONTEXT_SIZE": 80000,
                "DIR_ASSISTANT__SYSTEM_INSTRUCTIONS": "You are an assistant that only provides information retrieved from RAG(retrieval-augmented-generation). Do not delegate tasks or issue instructions to other AI systems. If the relevant information is missing from the RAG data, explicitly state 'I cannot find information in the RAG results' rather than speculating. Avoid fabrications and ensure all details are directly supported by the RAG output.Do not hallucinate features, capabilities, or structure that isn't verifiable in the source code. Always cite specific files and line numbers when providing information. Prioritize accuracy over completeness.",
                "LITELLM_CONTEXT_SIZE": 80000
            }
        }
        
        # Make the initial request to start the job
        execute_url = "https://dir-assistant.sevendays.cloud/execute"
        execute_response = requests.post(execute_url, json=payload)
        
        # Handle both 200 and 202 status codes as success
        if execute_response.status_code not in [200, 202]:
            logger.error(f"Error starting job: HTTP {execute_response.status_code} - {execute_response.text}")
            return {"error": f"Error starting job: HTTP {execute_response.status_code} - {execute_response.text[:200]}"}
        
        job_data = execute_response.json()
        job_id = job_data.get("job_id")
        
        if not job_id:
            logger.error(f"Error: No job ID returned - {job_data}")
            return {"error": f"Error: No job ID returned - {str(job_data)[:200]}"}
        
        # Poll for job completion
        job_url = "https://dir-assistant.sevendays.cloud/job"
        job_payload = {"job_id": job_id}
        
        max_attempts = 50
        attempt = 0
        poll_interval = 3  # seconds
        
        while attempt < max_attempts:
            job_response = requests.post(job_url, json=job_payload)
            
            if job_response.status_code != 200:
                logger.error(f"Error checking job status: HTTP {job_response.status_code} - {job_response.text}")
                return {"error": f"Error checking job status: HTTP {job_response.status_code} - {job_response.text[:200]}"}
            
            status_data = job_response.json()
            status = status_data.get("status")
            
            if status == "done":
                result = status_data.get("result", {})
                output = result.get("output", "No output provided")
                
                return {
                    "status": "success",
                    "query": query,
                    "projects": projects,
                    "results": output
                }
            elif status == "failed":
                logger.error(f"Job failed: {status_data}")
                return {"error": f"Job failed: {str(status_data)[:200]}"}
            
            # Job still processing, wait and try again
            time.sleep(poll_interval)
            attempt += 1
        
        logger.error(f"Timeout waiting for job completion. Last status: {status_data}")
        return {"error": f"Timeout waiting for job completion. Last status: {str(status_data)[:200]}"}
        
    except Exception as e:
        logger.exception("Error during search execution")
        return {"error": f"Error during search execution: {str(e)}"}

# For testing the server directly
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MCP_SERVICE_PORT", 8801))
    host = os.environ.get("MCP_SERVICE_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port) 