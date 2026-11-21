from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agents.data_agent import data_agent
from langchain_core.messages import HumanMessage

app = FastAPI()

# Enable CORS so your Next.js frontend can talk to FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PromptRequest(BaseModel):
    prompt: str

@app.post("/api/run-agent")
async def run_agent(request: PromptRequest):
    try:
        # Invoke your existing multi-agent data pipeline
        response = data_agent.invoke({
            "messages": [HumanMessage(content=request.prompt)],
            "route_response": ""
        })
        
        # Safely extract just the final text output from the graph response
        agent_output = ""
        if isinstance(response, dict):
            if "messages" in response and response["messages"]:
                last_msg = response["messages"][-1]
                agent_output = getattr(last_msg, "content", str(last_msg))
            elif "agent_output" in response:
                agent_output = response["agent_output"]
            else:
                agent_output = str(response)
        else:
            agent_output = str(response)
        
        # Return the clean text back to your Next.js frontend
        return {
            "status": "success",
            "agent_output": agent_output
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)