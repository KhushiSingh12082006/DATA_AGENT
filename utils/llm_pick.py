from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()


def pick_llm(level: str) -> ChatGroq:
    lvl = level.lower().strip()

    if lvl == "low":
        # Fast, lightweight model
        return ChatGroq(model="openai/gpt-oss-20b", temperature=0)

    elif lvl == "medium":
        # Balanced model for text-to-SQL
        return ChatGroq(model="openai/gpt-oss-20b", temperature=0)

    elif lvl == "high":
        # Heavy-duty 120B model for complex agent reasoning & code generation
        return ChatGroq(model="openai/gpt-oss-120b", temperature=0)

    else:
        raise ValueError(f"Unsupported level: {level}")
    

if __name__ == "__main__":
    llm_obj = pick_llm("high")
    print(llm_obj.invoke("What is the capital of France?").content)