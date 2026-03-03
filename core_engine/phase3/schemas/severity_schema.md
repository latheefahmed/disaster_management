# Phase 3.0 — Disaster Severity Schema

## 1. Purpose

Severity represents the **event-side physical intensity and spatial–temporal impact**
of a disaster. It is **independent of population, infrastructure, or vulnerability**.

Severity answers the question:

> “How strong, wide, and fast is the disaster itself?”

It does NOT answer:
- Who is affected
- How fragile the population is
- What resources are needed

Those are handled in later layers.

---

## 2. Core Definition

Severity is defined as a **time-indexed, spatially localized scalar field**:

S(d, t) ∈ ℝ⁺

Where:
- d = district
- t = discrete time step
- S = normalized severity score

Severity MUST satisfy:

- S(d, t) ≥ 0
- S(d, t₁) ≠ S(d, t₂) (time-variant)
- Independent of population metrics
- Comparable across districts for the same event

---

## 3. Severity Is Event-Centric

Severity depends ONLY on **hazard characteristics**, not on district properties.

Examples:
- Flood severity → rainfall anomaly, river overflow
- Cyclone severity → wind speed, pressure drop
- Heatwave severity → temperature deviation, duration
- Earthquake severity → magnitude, depth, distance

Population density, poverty, hospitals, etc. are explicitly excluded.

---

## 4. Severity Components (Abstracted)

Severity is decomposed into **four abstract components**:

### 4.1 Intensity (I)

Magnitude of the event at time t.

Examples:
- Rainfall percentile
- Wind speed category
- Temperature anomaly
- Earthquake magnitude

I(d, t) ∈ [0, 1]

---

### 4.2 Spatial Reach (R)

How much of the district is affected.

Examples:
- Flooded area fraction
- Wind field coverage
- Heatwave spatial persistence

R(d, t) ∈ [0, 1]

---

### 4.3 Temporal Escalation (E)

Rate of worsening or persistence over time.

Examples:
- Rising rainfall trend
- Sustained heatwave days
- Aftershock frequency

E(d, t) ∈ [0, 1]

---

### 4.4 Event Persistence (P)

Whether the event is transient or sustained.

Examples:
- Single-day spike vs multi-day event

P(d, t) ∈ [0, 1]

---

## 5. Severity Aggregation Formula

Severity is computed as a weighted aggregation:

S(d, t) = w₁·I(d, t) + w₂·R(d, t) + w₃·E(d, t) + w₄·P(d, t)

Subject to:

w₁ + w₂ + w₃ + w₄ = 1  
wᵢ ≥ 0

Weights are **explicit**, **documented**, and **versioned**.

---

## 6. Normalization Rules

- All component scores are normalized to [0, 1]
- No percentile normalization across districts (prevents dilution)
- Normalization is event-relative, not population-relative

---

## 7. Temporal Resolution

Severity is computed at discrete time steps:

t ∈ {T₀, T₁, T₂, …}

Where:
- T₀ = event onset
- Subsequent Tᵢ represent escalation or decay

Time granularity must be consistent across all districts.

---

## 8. Storage and Artifacts

Severity artifacts MUST include:

- severity_model.pkl
- severity_metadata.json
- severity_version.txt

Metadata MUST record:
- Disaster type
- Component definitions
- Weight values
- Normalization method
- Creation timestamp

---

## 9. Explicit Non-Goals

Severity MUST NOT:
- Use population
- Use vulnerability
- Use ethics
- Encode resource availability
- Predict demand

Any violation invalidates Phase 3.

---

## 10. Output Cont
