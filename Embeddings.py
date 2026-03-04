import json
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings,ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
import time

load_dotenv()

# client=genai.Client()
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001",task_type='RETRIEVAL_DOCUMENT')
vectorstore=Chroma(collection_name="shl_product_catalogue",persist_directory='shl_product_catalogue',embedding_function=embeddings)
# vectorstore.reset_collection()

with open("shl_llm_documents.json","r",encoding="utf-8") as f:   
    all_info=json.load(f)


# print(all_info[0])
def create_vectorstore():
    documents=[]
    for i,docs in enumerate(all_info):
        print(i)
        if (i+1)%70==0:
            vectorstore.add_documents(documents)
            documents=[]
            time.sleep(60)
            print("sleeping for 60s")
        doc = Document(
            page_content=(
                f"Title: {docs.get('title', '')}\n"
                f"Description: {docs.get('description', '')}\n"
                f"Test Types: {docs.get('test_types', '')}\n"
                f"Job Levels: {docs.get('job_levels', '')}\n"
                f"Assessment Length: {docs.get('assessment_length', '')}\n"
                f"Content: {docs.get('content', '')}"
            ),
            metadata={
                "title":             docs.get("title", ""),
                "source":            docs.get("source", ""),
                "remote_testing":    str(docs.get("remote_testing", "")),
                "adaptive_irt":      str(docs.get("adaptive_irt", "")),
                "test_types":        str(docs.get("test_types", [])),
                "description":       docs.get("description", ""),
                "job_levels":        str(docs.get("job_levels", [])),
                "languages":         str(docs.get("languages", [])),
                "assessment_length": docs.get("assessment_length", ""),
            },
        )
        documents.append(doc)

    
    print("Documents added")


if __name__=="__main__":
    create_vectorstore()