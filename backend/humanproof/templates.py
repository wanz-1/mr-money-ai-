"""Document templates for HumanProof AI document creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TemplateSection:
    name: str
    description: str
    required: bool = True
    min_words: int = 0
    max_words: int = 0
    subsections: List["TemplateSection"] = field(default_factory=list)
    guidance: str = ""


@dataclass
class DocumentTemplate:
    name: str
    template_type: str
    description: str
    sections: List[TemplateSection]
    target_words: int = 0
    citation_style: str = "apa"
    guidance: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "type": self.template_type,
            "description": self.description,
            "sections": [self._section_dict(s) for s in self.sections],
            "targetWords": self.target_words,
            "citationStyle": self.citation_style,
            "guidance": self.guidance,
        }

    def _section_dict(self, section: TemplateSection) -> Dict[str, object]:
        return {
            "name": section.name,
            "description": section.description,
            "required": section.required,
            "minWords": section.min_words,
            "maxWords": section.max_words,
            "guidance": section.guidance,
            "subsections": [self._section_dict(s) for s in section.subsections],
        }


TEMPLATES: Dict[str, DocumentTemplate] = {}


def _register(template: DocumentTemplate) -> None:
    TEMPLATES[template.template_type] = template


_register(DocumentTemplate(
    name="Research Paper",
    template_type="research_paper",
    description="Standard academic research paper structure.",
    target_words=6000,
    citation_style="apa",
    guidance="Present original research with clear methodology, results, and discussion.",
    sections=[
        TemplateSection("Title", "Descriptive title reflecting the main finding or topic.", min_words=5, max_words=20),
        TemplateSection("Abstract", "250-word summary of purpose, methods, results, and conclusions.", min_words=150, max_words=300),
        TemplateSection("Introduction", "Background, research question, and significance.", min_words=500, guidance="End with a clear hypothesis or research question."),
        TemplateSection("Literature Review", "Existing research and theoretical framework.", min_words=800, guidance="Organize thematically, not chronologically."),
        TemplateSection("Methodology", "Research design, data collection, and analysis approach.", min_words=600, guidance="Be specific enough for replication."),
        TemplateSection("Results", "Findings without interpretation.", min_words=600, guidance="Use tables and figures where appropriate."),
        TemplateSection("Discussion", "Interpretation, implications, limitations.", min_words=600, guidance="Connect findings to the literature review."),
        TemplateSection("Conclusion", "Summary of contributions and future directions.", min_words=300),
        TemplateSection("References", "Complete bibliography in the required citation style.", min_words=200),
    ],
))

_register(DocumentTemplate(
    name="Thesis",
    template_type="thesis",
    description="Graduate thesis or dissertation structure.",
    target_words=30000,
    citation_style="apa",
    guidance="Comprehensive scholarly work demonstrating independent research.",
    sections=[
        TemplateSection("Title Page", "Title, author, institution, date.", required=True),
        TemplateSection("Abstract", "300-word summary.", min_words=200, max_words=350),
        TemplateSection("Acknowledgments", "Thank collaborators and funding sources.", required=False),
        TemplateSection("Table of Contents", "Auto-generated from headings.", required=True),
        TemplateSection("Chapter 1: Introduction", "Problem statement, purpose, significance, research questions.", min_words=2000),
        TemplateSection("Chapter 2: Literature Review", "Comprehensive review of relevant scholarship.", min_words=4000),
        TemplateSection("Chapter 3: Methodology", "Research design, data collection, analysis methods.", min_words=3000),
        TemplateSection("Chapter 4: Results", "Presentation of findings.", min_words=3000),
        TemplateSection("Chapter 5: Discussion", "Interpretation, implications, limitations.", min_words=3000),
        TemplateSection("Chapter 6: Conclusion", "Summary, contributions, future research.", min_words=2000),
        TemplateSection("References", "Complete bibliography.", min_words=1000),
        TemplateSection("Appendices", "Supplementary materials.", required=False),
    ],
))

_register(DocumentTemplate(
    name="Grant Proposal",
    template_type="grant_proposal",
    description="NGO and research grant proposal.",
    target_words=5000,
    citation_style="apa",
    guidance="Persuasive, evidence-based, budget-aware.",
    sections=[
        TemplateSection("Cover Page", "Project title, applicant, amount, duration.", required=True),
        TemplateSection("Executive Summary", "Brief overview of the project.", min_words=300, max_words=500),
        TemplateSection("Statement of Need", "Problem description with evidence.", min_words=600, guidance="Use local data and statistics."),
        TemplateSection("Project Description", "Activities, timeline, methodology.", min_words=1200, guidance="Be specific about what will be done."),
        TemplateSection("Goals and Objectives", "Measurable outcomes.", min_words=300, guidance="Use SMART criteria."),
        TemplateSection("Evaluation Plan", "How success will be measured.", min_words=500),
        TemplateSection("Budget and Budget Narrative", "Costs and justification.", min_words=500),
        TemplateSection("Organizational Capacity", "Team qualifications and track record.", min_words=400),
        TemplateSection("Sustainability Plan", "Long-term viability after funding ends.", min_words=300),
        TemplateSection("References", "Supporting evidence and citations.", min_words=300),
    ],
))

_register(DocumentTemplate(
    name="Business Plan",
    template_type="business_plan",
    description="Comprehensive business plan structure.",
    target_words=8000,
    citation_style="harvard",
    guidance="Clear, data-driven, investor-focused.",
    sections=[
        TemplateSection("Executive Summary", "Business overview, mission, key highlights.", min_words=500, max_words=700, guidance="Write last, after all other sections."),
        TemplateSection("Company Description", "Legal structure, history, mission.", min_words=400),
        TemplateSection("Market Analysis", "Industry overview, target market, competition.", min_words=1000, guidance="Include market size data."),
        TemplateSection("Products/Services", "What you sell and its value proposition.", min_words=500),
        TemplateSection("Marketing Strategy", "Pricing, promotion, distribution.", min_words=600),
        TemplateSection("Operations Plan", "Day-to-day business processes.", min_words=500),
        TemplateSection("Management Team", "Key personnel and their qualifications.", min_words=400),
        TemplateSection("Financial Plan", "Projections, funding requirements, break-even.", min_words=800, guidance="Include 3-year projections."),
        TemplateSection("Appendix", "Supporting documents.", required=False),
    ],
))

_register(DocumentTemplate(
    name="Annual Report",
    template_type="annual_report",
    description="Organizational annual report.",
    target_words=5000,
    citation_style="chicago",
    guidance="Factual, transparent, stakeholder-focused.",
    sections=[
        TemplateSection("Chairperson's Message", "Leadership overview and vision.", min_words=300),
        TemplateSection("Organization Overview", "Mission, values, key activities.", min_words=400),
        TemplateSection("Year in Review", "Major achievements and milestones.", min_words=800),
        TemplateSection("Financial Report", "Revenue, expenses, balance sheet.", min_words=500),
        TemplateSection("Programs and Impact", "Outcomes and beneficiary stories.", min_words=800),
        TemplateSection("Governance", "Board composition and governance practices.", min_words=300),
        TemplateSection("Looking Ahead", "Strategic priorities for next year.", min_words=400),
        TemplateSection("Auditor's Report", "Independent financial audit opinion.", required=False),
    ],
))

_register(DocumentTemplate(
    name="Policy Document",
    template_type="policy",
    description="Organizational policy document.",
    target_words=3000,
    citation_style="chicago",
    guidance="Clear, enforceable, compliant.",
    sections=[
        TemplateSection("Policy Title and Number", "Identification and metadata.", required=True),
        TemplateSection("Purpose", "Why this policy exists.", min_words=100),
        TemplateSection("Scope", "Who and what is covered.", min_words=100),
        TemplateSection("Policy Statement", "The actual rules and requirements.", min_words=500, guidance="Use 'shall' for mandatory requirements."),
        TemplateSection("Procedures", "Step-by-step implementation.", min_words=400),
        TemplateSection("Roles and Responsibilities", "Who does what.", min_words=300),
        TemplateSection("Compliance", "Consequences of non-compliance.", min_words=200),
        TemplateSection("Review Schedule", "When and how this policy is reviewed.", min_words=100),
        TemplateSection("References", "Supporting legislation and standards.", min_words=100),
    ],
))

_register(DocumentTemplate(
    name="SOP",
    template_type="sop",
    description="Standard Operating Procedure.",
    target_words=2000,
    citation_style="ieee",
    guidance="Precise, actionable, auditable.",
    sections=[
        TemplateSection("SOP Header", "ID, version, effective date, author, approver.", required=True),
        TemplateSection("Purpose", "What this SOP achieves.", min_words=50),
        TemplateSection("Scope", "Applicability and limitations.", min_words=50),
        TemplateSection("Definitions", "Key terms and acronyms.", min_words=100),
        TemplateSection("Responsibilities", "Roles involved.", min_words=100),
        TemplateSection("Procedure", "Step-by-step instructions.", min_words=500, guidance="Number all steps. Be specific."),
        TemplateSection("Safety and Precautions", "Warnings and safety notes.", required=False),
        TemplateSection("References", "Related documents and standards.", min_words=100),
        TemplateSection("Revision History", "Change log.", required=True),
    ],
))

_register(DocumentTemplate(
    name="Resume",
    template_type="resume",
    description="Professional resume/CV.",
    target_words=1000,
    citation_style="none",
    guidance="Concise, achievement-focused, ATS-friendly.",
    sections=[
        TemplateSection("Contact Information", "Name, email, phone, LinkedIn.", required=True),
        TemplateSection("Professional Summary", "2-3 sentence career highlight.", min_words=30, max_words=60),
        TemplateSection("Work Experience", "Reverse-chronological roles and achievements.", min_words=200, guidance="Quantify achievements where possible."),
        TemplateSection("Education", "Degrees, institutions, dates.", min_words=80),
        TemplateSection("Skills", "Technical and soft skills.", min_words=50),
        TemplateSection("Certifications", "Professional certifications.", required=False),
        TemplateSection("Projects", "Notable projects or publications.", required=False),
    ],
))

_register(DocumentTemplate(
    name="Contract",
    template_type="contract",
    description="Standard business contract.",
    target_words=4000,
    citation_style="none",
    guidance="Precise legal language, clear obligations.",
    sections=[
        TemplateSection("Parties", "Identifying information for all parties.", required=True),
        TemplateSection("Recitals", "Background and purpose of the agreement.", min_words=200),
        TemplateSection("Definitions", "Defined terms used throughout.", min_words=300),
        TemplateSection("Terms and Conditions", "Main obligations and rights.", min_words=1500, guidance="Organize by subject matter."),
        TemplateSection("Payment Terms", "Amounts, schedules, late fees.", min_words=200),
        TemplateSection("Term and Termination", "Duration and exit conditions.", min_words=200),
        TemplateSection("Confidentiality", "Non-disclosure obligations.", min_words=200),
        TemplateSection("Dispute Resolution", "Arbitration, mediation, jurisdiction.", min_words=200),
        TemplateSection("General Provisions", "Severability, entire agreement, amendments.", min_words=200),
        TemplateSection("Signatures", "Execution block.", required=True),
    ],
))


def get_template(template_type: str) -> Optional[DocumentTemplate]:
    return TEMPLATES.get(template_type)


def list_templates() -> List[Dict[str, object]]:
    return [t.to_dict() for t in TEMPLATES.values()]


def generate_template_content(template_type: str) -> Optional[str]:
    template = get_template(template_type)
    if not template:
        return None
    lines = [f"# {template.name}", ""]
    for section in template.sections:
        lines.append(f"## {section.name}")
        lines.append(f"*{section.description}*")
        if section.guidance:
            lines.append(f"**Guidance:** {section.guidance}")
        if section.min_words:
            lines.append(f"*Target: {section.min_words}+ words*")
        lines.append("")
        if section.subsections:
            for sub in section.subsections:
                lines.append(f"### {sub.name}")
                lines.append(f"*{sub.description}*")
                lines.append("")
        lines.append("[Your content here]")
        lines.append("")
    return "\n".join(lines)
