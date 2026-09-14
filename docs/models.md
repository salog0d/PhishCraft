### Fine-Tuned Models (5)

These models have been specifically trained on cybersecurity data for red team tasks.

#### 1. RavenX-CyberAgent
- **Model Link:** [deadbydawn101/RavenX-CyberAgent-v6.2-Experimental-GGUF](https://huggingface.co/deadbydawn101/RavenX-CyberAgent-v6.2-Experimental-GGUF) 
- **Base Model:** `huihui-ai/Huihui-Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated` 
- **Key Detail:** A 35B Mixture-of-Experts (MoE) model where only ~3B parameters activate per token. It executes the structured **RATH protocol** for security assessments and is trained on **745,000+** security examples . The recommended quantized version is ~20.7 GB.

#### 2. Pentest-7B (VEXT)
- **Model Link:** [VextLabsinc/pentest-7b](https://huggingface.co/VextLabsinc/pentest-7b) 
- **Base Model:** `Qwen/Qwen2.5-7B-Instruct` 
- **Key Detail:** Trained on **260,000+** curated examples from real pentesting engagements, CTF challenges, and bug bounty programs. Outperforms its base model significantly on security benchmarks (SecBench: 82.4% vs 61.2%) . Designed to parse output from 25+ security tools.

#### 3. BugTraceAI-CORE-G4-Apex
- **Model Link:** [BugTraceAI/BugTraceAI-Apex-G4-26B-Q4](https://huggingface.co/BugTraceAI/BugTraceAI-Apex-G4-26B-Q4) 
- **Base Model:** `TrevorJS/gemma-4-26B-A4B-it-uncensored` 
- **Key Detail:** A 26B MoE model fine-tuned via **DPO** (Direct Preference Optimization) on a dataset of elite HackerOne reports and malware methodologies. Features an injected Opus-style reasoning engine that forces step-by-step analysis . Optimized to run on 12GB VRAM GPUs.

#### 4. Dolphin3-Cyber-8B
- **Model Link:** [RavichandranJ/Dolphin3-Cyber-8B-GGUF](https://huggingface.co/RavichandranJ/Dolphin3-Cyber-8B-GGUF) 
- **Base Model:** `huihui-ai/Dolphin3.0-Llama3.1-8B-abliterated` 
- **Key Detail:** An 8B parameter fine-tune via **LoRA** that is fully uncensored and trained on OWASP Top 10, MITRE ATT&CK, and CVE datasets. Runs efficiently on consumer GPUs with 4GB+ VRAM and is available in 11 quantized versions .

#### 5. Security-SLM (Gemma-4-E2B)
- **Model Link:** [entrick/Security-SLM-Gemma-4-E2B-it-GGUF](https://huggingface.co/entrick/Security-SLM-Gemma-4-E2B-it-GGUF) 
- **Base Model:** `google/gemma-4-E2B` 
- **Key Detail:** Specialized in **AI security** (prompt injection, RAG poisoning, MCP tool poisoning). Trained on 1,000 curated instruction/response pairs. Provides a structured "Reasoning Summary" before its answer, making it suitable for auditing agentic workflows .

---

### Non-Fine-Tuned Foundation Models (5)

These are general-purpose models that can be used as a baseline for comparison.

#### 1. Qwen3.6-35B-A3B (Base)
- **Model Link:** [Qwen/Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- **Base Model:** N/A (This is the foundation for RavenX-CyberAgent)
- **Key Detail:** A powerful 35B MoE model that can be served via vLLM on Azure. It supports **function calling**, making it suitable for agentic pipelines.

#### 2. Gemma 4 (26B)
- **Model Link:** [google/gemma-4](https://huggingface.co/google/gemma-4)
- **Base Model:** N/A (This is the foundation for BugTraceAI-CORE-G4-Apex)
- **Key Detail:** A 26B parameter model from Google that has been "uncensored" variants created from it. Available for deployment on Azure AI Foundry.

#### 3. Llama 3.1 (8B or 70B)
- **Model Link:** [meta-llama/Llama-3.1-8B](https://huggingface.co/meta-llama/Llama-3.1-8B)
- **Base Model:** N/A (This is the foundation for Dolphin3-Cyber-8B)
- **Key Detail:** A popular foundation model that can be deployed in various configurations. Available via Azure AI Foundry.

#### 4. DeepSeek-V3
- **Model Link:** [deepseek-ai/DeepSeek-V3](https://huggingface.co/deepseek-ai/DeepSeek-V3)
- **Base Model:** N/A
- **Key Detail:** Known for its strong reasoning capabilities and has been observed being used for autonomous offensive tasks in the wild. Available via **Azure AI Foundry**.

#### 5. Qwen2.5-7B-Instruct
- **Model Link:** [Qwen/Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)
- **Base Model:** N/A (This is the foundation for VEXT Pentest-7B)
- **Key Detail:** The base model used for the VEXT Pentest-7B. Good baseline to compare the effect of fine-tuning on the same architecture.

---

