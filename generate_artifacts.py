import os
import glob
import json

base_dir = r"c:\Users\LATHEEF\Desktop\disaster_management"
artifacts_dir = os.path.join(base_dir, "artifacts")
os.makedirs(artifacts_dir, exist_ok=True)

final_doc_path = os.path.join(artifacts_dir, "FINAL_COMPREHENSIVE_REPORT.md")

documentation_content = """# Disaster Management System - Comprehensive Report

## 1. Introduction & Proposed Methodology

The disaster management system utilizes a multi-layered architecture designed to handle disaster resource allocation in a structured and ethical manner. The proposed methodology leverages an AI-assisted linear programming optimization engine to distribute scarce resources fairly among affected districts based on demand, vulnerability, and urgency. 

## 2. System Design & Architecture (Image to Text Conversions)

### 1️⃣ System Architecture Diagram
The architecture consists of four major layers:
1. **Request Layer**
   District authorities submit: Resource demand, Urgency level, Priority classification, Vulnerability indicators. Each district acts as an autonomous agent.
2. **Central Processing Layer**
   The central coordinator: Collects available stock from district, state, and national levels; Aggregates demand data; Applies ethical fairness constraints; Formulates the Linear Programming optimization problem.
3. **Allocation Layer**
   The optimization engine: Runs the LP solver (PuLP with CBC); Generates optimal allocation values; Distributes resources hierarchically (District → State → National).
4. **Audit & Reporting Layer**
   The system: Logs all allocation decisions; Stores fairness metrics; Records unmet demand explicitly; Enables transparency and verification.
   This architecture ensures scalability, transparency, and deterministic outputs.

### 2️⃣ System Workflow Diagram
The workflow operates in five structured phases:
- **Phase 1: Request Phase** - Districts submit resource demands through the user interface, including urgency and vulnerability levels.
- **Phase 2: Processing Phase** - The central system aggregates all demands, collects available inventory, applies fairness rules, and prepares optimization constraints.
- **Phase 3: Optimization Phase** - The LP solver minimizes total unmet demand, enforces stock limits, and applies fairness-aware distribution rules.
- **Phase 4: Allocation Phase** - Resources are distributed first from district level, then escalated to state level, and finally from national level if needed.
- **Phase 5: Auditing Phase** - All decisions are logged, and fairness metrics are calculated for review.

### 8️⃣ Algorithms Diagram
The system uses seven core algorithms:
1. **AI-Assisted Demand Estimation**: Predicts district-level demand using disaster severity features.
2. **Disaster Severity Prediction**: Uses feature vector $X_d$ and trained model $g_θ$ to estimate disaster intensity.
3. **Vulnerability Scoring**: Computes district vulnerability using demographic and geographic indicators.
4. **Demand Aggregation**: Aggregates weighted demand across all districts.
5. **Linear Programming Optimization**: 
   - *Objective*: Minimize total unmet demand.
   - *Constraints*: Allocation ≤ Demand, Allocation ≤ Available Supply, Fairness constraint, Hierarchical supply constraint.
6. **Hierarchical Resource Allocation**: Ensures escalation logic from district → state → national.
7. **Fairness-Aware Allocation**: Prevents over-allocation to dominant districts.

### 9️⃣ Mathematical Model
- **Decision Variables**: Amount of resource allocated to each district.
- **Objective Function**: Minimize total unmet demand across all districts.
- **Demand Balance Constraints**: Ensure allocation does not exceed demand.
- **Stock Constraints**: Ensure allocation does not exceed available supply.
- **Fairness Constraints**: Introduce proportional distribution rules to prevent bias.

## 3. Experimental Setup

The system was deployed locally using:
- **Backend**: Python, FastAPI server
- **Database**: SQLite database
- **Optimization Engine**: PuLP optimization library, CBC solver
- **Frontend**: React/Vite (from existing structure)
Test scenarios were simulated using CSV/JSON seed data. Results were visualized on a dashboard showing allocation results, fairness metrics, and unmet demand tracking.

## 4. Evaluation and Execution of the Project

The system was evaluated extensively under stress to measure evaluation metrics, fairness handling under severe shortage, and robustness.

### Evaluation Metrics and Logs
*(Appended dynamically from workspace logs)*

"""

with open(final_doc_path, "w", encoding="utf-8") as f:
    f.write(documentation_content)

# Let's collect existing evaluation metrics reports
reports_to_copy = glob.glob(os.path.join(base_dir, "backend", "*REPORT*.md")) + \
                   glob.glob(os.path.join(base_dir, "*REPORT*.md"))

with open(final_doc_path, "a", encoding="utf-8") as f_out:
    f_out.write("\n## 5. Result Analysis & System Reports\n\n")
    for r in reports_to_copy:
        f_out.write(f"\n### File: {os.path.basename(r)}\n\n")
        try:
            with open(r, "r", encoding="utf-8") as f_in:
                 content = f_in.read()
                 # truncate if too large to avoid huge massive files, 
                 # but prompt user wants all of it
                 f_out.write(content)
        except Exception as e:
            f_out.write(f"Error reading file: {e}\n")

# Adding Visual Graphs / Charts textual descriptions
graphs_text = """
## 6. Performance Comparison & Visual Graphs Interpretations

### 3️⃣ Escalation Profile by Supply Level 
Shows how resource allocation changes as supply levels vary.
- **Sufficient Supply**: Almost zero unmet demand.
- **Reduced Supply**: Allocation prioritizes critical districts.
- **Critically Low Supply**: Fairness constraint ensures balanced suffering rather than extreme bias. Demonstrates dynamic adaptation.

### 4️⃣ Fairness Distribution Across Districts
- High population districts do not dominate allocation.
- Vulnerability-adjusted fairness ensures balanced distribution.
- Allocation follows ethical weighting rather than raw demand alone.

### 5️⃣ Scenario Outcomes: Allocation vs Unmet Demand (Side-by-Side View)
- Compares allocated resources and unmet demand.
- **Balanced scenarios**: Allocation meets most demand.
- **Shortage scenarios**: Unmet demand increases proportionally. Explicitly displays unmet demand.

### 6️⃣ Scenario Outcomes: Allocation vs Unmet Demand (Stacked View)
Highlights the proportion of shortage, fair distribution of limited supply, and ethical balancing between districts.

### 7️⃣ S6: Total Failure Scenario – Top Districts by Unmet Demand
Worst-case disaster where supply is extremely limited.
- Unmet demand increases across all districts.
- The gap remains proportionally balanced.
- No district receives extreme preference.

## 7. Conclusion

The developed disaster management system successfully addresses the complex, high-stakes problem of resource allocation during emergencies. Through an integration of hierarchical requests, AI-based demand constraints, and fairness-aware Linear Programming, the platform proves robust against severe stock shortages. The extensive stress-testing, automated regression verification, and explicit unmet demand tracking satisfy the goals of transparency, scalability, and ethical determinism required in real-case deployments.
"""

with open(final_doc_path, "a", encoding="utf-8") as f_out:
    f_out.write(graphs_text)

# Let's copy some json metrics to the artifacts dir as well
json_reports = glob.glob(os.path.join(base_dir, "backend", "*.json")) + glob.glob(os.path.join(base_dir, "*.json"))
for jf in json_reports:
    try:
        dest = os.path.join(artifacts_dir, os.path.basename(jf))
        import shutil
        shutil.copy2(jf, dest)
    except:
        pass
        
txt_reports = glob.glob(os.path.join(base_dir, "backend", "*.txt")) + glob.glob(os.path.join(base_dir, "*.txt"))
for txt in txt_reports:
    try:
        dest = os.path.join(artifacts_dir, os.path.basename(txt))
        import shutil
        shutil.copy2(txt, dest)
    except:
        pass

print("Artifacts generated successfully.")
