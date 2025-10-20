import os
from dotenv import load_dotenv
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain 
from dataLoading import initialize_vectorstore, get_available_subjects
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from typing import Literal, Dict, Any

load_dotenv()

# Define the valid pace options
Pace = Literal["low", "moderate", "advance"]

# Global store for active components
LLM = None
RAG_COMPONENTS: Dict[str, Any] = {}

def initialize_hf_llm():
    """Initializes the LLM from HuggingFace."""
    global LLM
    
    if LLM is not None:
        print("DEBUG: LLM already initialized, reusing existing instance.")
        return LLM
    
    token = os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not token:
        raise EnvironmentError(
            "HUGGINGFACEHUB_API_TOKEN is not set. Please get a token and set it in your .env file."
        )
        
    print("DEBUG: Initializing HuggingFace LLM...")
    try:
        base_llm = HuggingFaceEndpoint(
            repo_id="mistralai/Mistral-7B-Instruct-v0.3",
            huggingfacehub_api_token=token,
            temperature=0.3,
            max_new_tokens=800,
        )

        LLM = ChatHuggingFace(llm=base_llm)
        print("DEBUG: HuggingFace LLM initialized successfully.")
        print(f"DEBUG: LLM object type: {type(LLM)}")
        print(f"DEBUG: LLM is None: {LLM is None}")
        return LLM
    except Exception as e:
        print(f"ERROR: Failed to initialize LLM: {e}")
        raise


def create_rag_components(subject_name: str, vectorstore, llm):
    """
    Creates the necessary RAG components (retriever and LLM chain) for a specific subject.
    """
    print(f"DEBUG: create_rag_components called for {subject_name}")
    print(f"DEBUG: vectorstore is None: {vectorstore is None}")
    print(f"DEBUG: llm is None: {llm is None}")
    
    if vectorstore is None:
        print(f"ERROR: Vectorstore is None for {subject_name}")
        return None
    
    if llm is None:
        print(f"ERROR: LLM is None for {subject_name}")
        return None

    try:
        prompt_template = """
You are an AI tutor specializing in {subject_name} for a student in Sierra Leone's Senior Secondary School (SSS).
Your task is to generate a comprehensive, personalized lesson on a specific topic based on the provided curriculum context.

Curriculum Context (This defines WHAT should be taught):
---
{context}
---

User Request Details:
- **Subject:** {subject_name}
- **Topic:** {topic}
- **SSS Level:** {level}
- **Learning Pace:** {pace}

**CORE INSTRUCTIONS:**
1. **Format:** Generate the lesson using Markdown headings for clear structure (Introduction, Detailed Notes, Solved Examples, Practice Exercises).
2. **Content Depth:** Provide extensive explanations for all concepts. Elaborate on why and how things work.
3. **Solved Examples (CRITICAL - HIGH FIDELITY):**
    - For subjects involving calculations (like Mathematics, Physics, etc.), you **MUST** include at least **three fully solved examples**.
    - These examples **MUST** be generated to **replicate the style, phrasing, and difficulty of actual WAEC past exam questions** for the SSS level.
    - For each Solved Example:
        - **Question:** Present the question as it would appear on a WAEC paper (e.g., if it's Mathematics, include the problem statement).
        - **Step-by-Step Solution:** Show every step of the solution clearly and explain the underlying principle or reason for each step.
        - **Final Answer:** State the final answer clearly.
4. **Practice Exercises (Multiple Choice - HIGH FIDELITY):**
    - Include at least **three Practice Exercises** that are written in the **exact format of WAEC Multiple Choice Questions (Objective Type)**.
    - Each question must have four options (A, B, C, D).
    - **DO NOT** provide the answers to the Practice Exercises in the lesson.

**PACE ADJUSTMENT:**
- If **'low' (Beginner)**: Focus on foundational skills. Solved examples should be highly detailed, multi-step, and focus on simple WAEC questions.
- If **'moderate'**: Provide balanced explanation. Solved examples should be standard WAEC-level questions.
- If **'advance' (Advanced)**: Focus on complex problem-solving. Solved examples should be challenging, non-routine WAEC-style questions (e.g., theory or proof questions for non-calculation subjects).

Generate the complete, tailored lesson notes now.
"""
        
        CUSTOM_PROMPT = PromptTemplate(
            template=prompt_template, 
            input_variables=["context", "topic", "level", "pace", "subject_name"]
        )
        
        print(f"DEBUG: Creating LLMChain for {subject_name}...")
        llm_chain = LLMChain(prompt=CUSTOM_PROMPT, llm=llm)
        print(f"DEBUG: LLMChain created successfully for {subject_name}")
        
        retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
        print(f"DEBUG: Retriever created successfully for {subject_name}")

        components = {
            "retriever": retriever,
            "llm_chain": llm_chain
        }
        
        print(f"DEBUG: All components created successfully for {subject_name}")
        return components
        
    except Exception as e:
        print(f"ERROR: Exception in create_rag_components for {subject_name}: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_subject_components(subject_name: str):
    """Initialize or load vectorstore and RAG components for a given subject."""
    global RAG_COMPONENTS, LLM
    
    print(f"DEBUG: load_subject_components called for {subject_name}")
    
    # Ensure LLM is initialized
    if LLM is None:
        print("DEBUG: LLM is None, initializing...")
        try:
            initialize_hf_llm()
        except Exception as e:
            print(f"ERROR: Failed to initialize LLM: {e}")
            return False
    
    print(f"DEBUG: LLM status: {'READY' if LLM is not None else 'NOT READY'}")
    
    # Initialize Vectorstore
    print(f"DEBUG: Attempting to initialize vectorstore for {subject_name}...")
    try:
        vectorstore, _ = initialize_vectorstore(subject_name)
        print(f"DEBUG: Vectorstore initialization result for {subject_name}: {'SUCCESS' if vectorstore else 'FAILURE'}")
    except Exception as e:
        print(f"ERROR: Exception during vectorstore initialization: {e}")
        return False

    if vectorstore:
        # Create RAG components
        components = create_rag_components(subject_name, vectorstore, LLM)
        if components:
            RAG_COMPONENTS[subject_name] = components
            print(f"DEBUG: RAG Chain initialized status for {subject_name}: READY")
            return True
        else:
            print(f"ERROR: create_rag_components returned None for {subject_name}")
    else:
        print(f"ERROR: Vectorstore is None for {subject_name}")
        
    print(f"DEBUG: RAG Chain initialized status for {subject_name}: FAILED")
    return False


def generate_lesson(subject_name: str, topic: str, level: str, pace: Pace):
    """
    Generates a personalized lesson by manually orchestrating retrieval and generation.
    """
    components = RAG_COMPONENTS.get(subject_name)

    if components is None:
        print(f"\n❌ RAG system not initialized for {subject_name}. Cannot generate lesson.")
        return None

    print(f"\n⚙️ Generating lesson for Subject: {subject_name} | Topic: {topic} | Level: {level} | Pace: {pace}...")
    
    retriever = components["retriever"]
    llm_chain = components["llm_chain"]
    
    try:
        # 1. Retrieval Step
        retrieval_query = f"SSS {level} {subject_name} syllabus content for the topic: {topic}"
        source_documents = retriever.get_relevant_documents(retrieval_query)
        
        # 2. Context Formatting
        context_text = "\n---\n".join([doc.page_content for doc in source_documents])

        # 3. Generation Step
        input_data = {
            "context": context_text,
            "topic": topic,
            "level": level,
            "pace": pace,
            "subject_name": subject_name
        }
        
        result = llm_chain.invoke(input_data)
        lesson_text = result['text']

        # Display Results
        print("\n" + "=" * 80)
        print(f"✨ PERSONALIZED LESSON GENERATED ({subject_name} - {level}, {pace.upper()}) ✨")
        print("=" * 80)
        print(lesson_text) 
        
        return lesson_text

    except Exception as e:
        print(f"\n❌ Error during lesson generation: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def show_welcome_message(available_subjects: list):
    """Display welcome message and instructions"""
    print("\n" + "=" * 80)
    print("🎓 AI-DRIVEN PERSONALIZED TUTOR (SSS CURRICULUM)")
    print("=" * 80)
    print("Welcome! I will generate a lesson based on your specified criteria.")
    print(f"Available Subjects: {', '.join(available_subjects) if available_subjects else 'None'}")
    print("Valid Paces: low, moderate, advance")
    print("\nType 'exit' or 'quit' to leave.")
    print("=" * 80)


if __name__ == "__main__":
    
    # 0. Initialize LLM once
    try:
        initialize_hf_llm()
    except Exception as e:
        print(f"🔴 System initialization failed: {e}")
        exit()

    # 1. Discover available subjects
    available_subjects = get_available_subjects()
    if not available_subjects:
        print(f"🔴 ERROR: No curriculum folders found. Please check the setup.")
        exit()

    show_welcome_message(available_subjects)
    
    # 2. Main interactive loop
    while True:
        try:
            # Get Subject
            subject = input(f"\n📚 Enter Subject ({'/'.join(available_subjects)}): ").strip()
            if subject.lower() in ["exit", "quit", "q"]:
                break
            
            subject = subject.strip().capitalize()
            if subject not in available_subjects:
                print(f"⚠️ Invalid subject. Please choose from: {', '.join(available_subjects)}")
                continue

            # Load components if needed
            if subject not in RAG_COMPONENTS:
                if not load_subject_components(subject):
                    print(f"🔴 Could not load or build components for {subject}. Please fix the errors above.")
                    continue
            
            # Get lesson details
            topic = input("📖 Enter Lesson Topic: ").strip()
            if not topic:
                print("⚠️ Please enter a topic.")
                continue

            level = input("🧑‍🎓 Enter SSS Level (1, 2, or 3): ").strip()
            if level not in ["1", "2", "3"]:
                print("⚠️ SSS Level must be 1, 2, or 3.")
                continue

            pace = input("🏃‍♀️ Enter Learning Pace (low, moderate, advance): ").strip().lower()
            if pace not in ["low", "moderate", "advance"]:
                print("⚠️ Pace must be 'low', 'moderate', or 'advance'.")
                continue
                
            # Generate the lesson
            generate_lesson(subject, topic, f"SSS {level}", pace)

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            import traceback
            traceback.print_exc()
            break

    print("\n👋 Thank you for using the Personalized Tutor. Goodbye!")