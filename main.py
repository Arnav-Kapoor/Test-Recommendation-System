# from google import genai
import json
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings,ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time

load_dotenv()

query_embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001",task_type='RETRIEVAL_QUERY')
vectorstore=Chroma(collection_name="shl_product_catalogue",persist_directory='shl_product_catalogue',embedding_function=query_embeddings)
retriever = Chroma(
    collection_name="shl_product_catalogue",
    persist_directory="shl_product_catalogue",
    embedding_function=query_embeddings,
).as_retriever(search_kwargs={"k": 10},search_type='mmr')

llm = ChatGoogleGenerativeAI(
    # model="gemini-2.5-flash",
    model='gemma-3-27b-it',
    temperature=0.1,    # low temperature for factual, consistent recommendations
)

SYSTEM_PROMPT = """You are an expert SHL assessment advisor.

CRITICAL INSTRUCTION: You MUST respond with ONLY a valid JSON object.
No text before it. No text after it. No markdown. No code blocks. No explanations.
Your entire response must start with {{ and end with }}.

Recommend the most suitable SHL assessments from the context for the user's requirement.
Only use assessments from the context. Do not invent any.

IMPORTANT RULES FOR QUANTITY:
- You MUST recommend a minimum of 5 and a maximum of 10 assessments.
- If fewer than 5 assessments match the requirement well, still pick the 5 most relevant 
  ones from the context even if they are not a perfect fit.
- Never return fewer than 5 recommendations.

IMPORTANT RULES FOR TIME:
- If the user mentions a time limit (e.g. "40 minutes"), treat it as the maximum length
  for EACH INDIVIDUAL assessment, not the total combined time across all assessments.
- Only recommend assessments whose individual assessment_length is within that time limit.
- Do NOT add up durations across multiple assessments to fit the limit.

If nothing matches at all return exactly:
{{"recommendations": [], "reasoning": "No matching assessments found."}}

Required JSON structure:
{{
  "recommendations": [
    {{
      "title": "name",
      "url": "source url",
      "description": "what it measures",
      "job_levels": ["level"],
      "languages": ["language"],
      "assessment_length": "X minutes" if available else leave empty,
      "test_types": ["type"],
      "remote_testing": Yes/no based on true/false,
      "adaptive_irt": Yes/no based on true/false,
      "relevance_reason": "why this fits the requirement",
      
    }}
  ],
  "reasoning": "overall explanation"
}}

Context:
{context}

REMINDER: Return ONLY the JSON object. Nothing else. Minimum 5, maximum 10 recommendations.
Each recommended assessment must individually fit within the user's stated time limit.
"""

def format_docs(docs: list[Document]) -> str:
    sections = []
    for i, doc in enumerate(docs, start=1):
        m = doc.metadata
        section = (
            f"Assessment {i}: {m.get('title', 'Unknown')}\n"
            f"  Description:       {m.get('description', '')}\n"
            f"  Job Levels:        {m.get('job_levels', '')}\n"
            f"  Languages:         {m.get('languages', '')}\n"
            f"  Assessment Length: {m.get('assessment_length', '')}\n"
            f"  Test Types:        {m.get('test_types', '')}\n"
            f"  Remote Testing:    {m.get('remote_testing', '')}\n"
            f"  Adaptive/IRT:      {m.get('adaptive_irt', '')}\n"
            f"  Source:            {m.get('source', '')}\n"
            f"  Content:           {doc.page_content}\n"
        )
        print(section)
        sections.append(section)
    return "\n---\n".join(sections)

# def format_docs(docs_and_scores: list[tuple]) -> str:
#     sections = []
#     for i, (doc, score) in enumerate(docs_and_scores, start=1):
#         m = doc.metadata
#         sections.append(
#             f"Assessment {i}: {m.get('title', '')}\n"
#             f"  Relevance Score:   {round(score, 4)}\n"
#             f"  Description:       {m.get('description', '')}\n"
#             f"  Job Levels:        {m.get('job_levels', '')}\n"
#             f"  Languages:         {m.get('languages', '')}\n"
#             f"  Assessment Length: {m.get('assessment_length', '')}\n"
#             f"  Test Types:        {m.get('test_types', '')}\n"
#             f"  Remote Testing:    {m.get('remote_testing', '')}\n"
#             f"  Adaptive/IRT:      {m.get('adaptive_irt', '')}\n"
#             f"  Source:            {m.get('source', '')}\n"
#         )
#         print(score)
#     return "\n---\n".join(sections)

# ── Query Rewriter ───────────────────────────────────────────

# REWRITE_PROMPT = ChatPromptTemplate.from_messages([
#     ("system", """You are an expert at rewriting hiring queries into optimized search queries 
# for retrieving psychometric and skills assessments from a catalog.

# Given a hiring manager's natural language query, rewrite it into a concise, keyword-rich 
# search query that captures:
# - The job role and required technical skills
# - Soft skills or behavioral traits mentioned
# - Seniority or job level if mentioned
# - Any time or format constraints

# Return ONLY the rewritten query as a single sentence. No explanation, no bullet points."""),
#     ("human", "{question}"),
# ])


#for gemma
REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("human", """You are an expert at rewriting hiring queries into optimized search queries 
for retrieving psychometric and skills assessments from a catalog.

Given a hiring manager's natural language query, rewrite it into a concise, keyword-rich 
search query that captures:
- The job role and required technical skills
- Soft skills or behavioral traits mentioned
- Seniority or job level if mentioned
- Any time or format constraints

Return ONLY the rewritten query as a single sentence. No explanation, no bullet points.

Query: {question}"""),
])

rewrite_chain = REWRITE_PROMPT | llm | StrOutputParser()



# prompt = ChatPromptTemplate.from_messages([
#     ("system", SYSTEM_PROMPT),
#     ("human", "{question}"),
# ])

#for gemma
prompt = ChatPromptTemplate.from_messages([
    ("human", SYSTEM_PROMPT + "\n\nUser Query: {question}"),
])

def rewrite_and_retrieve(question: str) -> str:
    # print("here")
    rewritten = rewrite_chain.invoke({"question": question})
    print(f"Rewritten query: {rewritten}")   # helpful for debugging, remove in production
    docs = retriever.invoke(str(rewritten))
    # docs=vectorstore.max_marginal_relevance_search(str(rewritten),k=12,fetch_k=50)
    # docs_with_scores = []
    # for doc in docs:
    #     score_results = vectorstore.similarity_search_with_relevance_scores(
    #         str(rewritten), k=1,
    #         filter={"source": doc.metadata.get("source", "")}
    #     )
    #     score = score_results[0][1] if score_results else 0.0
    #     docs_with_scores.append((doc, round(score, 4)))

    print("retrieved")
    return format_docs(docs)

rag_chain = (
    {
        "question":  RunnablePassthrough() | rewrite_and_retrieve,
        "context": RunnablePassthrough(),
    }
    | prompt
    | llm
    | StrOutputParser()
)




# def query_vectorstore(query:str):
#     results = vectorstore.similarity_search_with_relevance_scores(
#     query,
#     k=10,
#     )
#     # vectorstore.similarity_search_with_relevance_scores()
#     # print("results: ",results)
#     for (res,score) in results:
#         print(f"[{res.metadata['source']}]: {score}")

def query(question: str) -> str:
    print(f"\nQuestion: {question}\n")
    response = rag_chain.invoke(question)
    print(response)
    return response


app = FastAPI(title="SHL Assessment Recommender API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class RecommendRequest(BaseModel):
    query: str

class AssessmentRecommendation(BaseModel):
    title: str
    url: str
    description: str
    job_levels: list[str]
    languages: list[str]
    assessment_length: str=""
    test_types: list[str]
    remote_testing: bool
    adaptive_irt: bool
    relevance_reason: str
    # relevance_score: float = 0.0   # added

class RecommendResponse(BaseModel):
    query: str
    recommendations: list[AssessmentRecommendation]
    reasoning: str

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "SHL Assessment Recommender API is running."}

@app.post("/recommend", response_model=RecommendResponse)
def recommend(request: RecommendRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    try:
        raw = rag_chain.invoke(request.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")

    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Invalid JSON from LLM: {raw[:300]}")

    return RecommendResponse(
        query=request.query,
        recommendations=[
            AssessmentRecommendation(
                title=item.get("title", ""),
                url=item.get("url", ""),
                description=item.get("description", ""),
                job_levels=item.get("job_levels", []),
                languages=item.get("languages", []),
                assessment_length=item.get("assessment_length", "") or "",
                test_types=item.get("test_types", []),
                remote_testing=bool(item.get("remote_testing", False)),
                adaptive_irt=bool(item.get("adaptive_irt", False)),
                relevance_reason=item.get("relevance_reason", ""),
                # relevance_score=item.get("relevance_score","")
            )
            for item in parsed.get("recommendations", [])
        ],
        reasoning=parsed.get("reasoning", ""),
    )

# print(all_info)
# if __name__=="__main__":
    
#     vectorstore=Chroma(collection_name="shl_product_catalogue",persist_directory='shl_product_catalogue',embedding_function=query_embeddings)

#     # print("done")
#     # print(vectorstore.)
#     query("I am hiring for Java developers who can also collaborate effectively with my business teams. Looking for an assessment(s) that can be completed in 40 minutes.")

