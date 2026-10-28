# Final Year Project Stage-II Report — VendorMap

This directory (`report/`) contains the complete, institute-compliant \LaTeX{} source code for the Final Year Project (FYP) Stage-II Report for **VendorMap – A Smart Vendor Relocation and Zone Recommendation System**.

The report strictly adheres to the official format prescribed by the **Department of Information Technology, K. K. Wagh Institute of Engineering Education and Research, Nashik-3** (Academic Year 2026–2027) for the Bachelor of Technology (B.Tech) degree.

---

## 1. Directory Structure

```text
report/
├── main.tex                 # Master LaTeX document combining all chapters and front/back matter
├── references.bib           # IEEE-compliant BibTeX bibliography file (18 verified entries)
├── README.md                # Comprehensive compilation, customization, and asset guide
├── chapters/                # Modular chapter files included in prescribed sequence
│   ├── titlepage.tex        # Official Title Page (Institute, Department, Students, Guide)
│   ├── certificate.tex      # Academic Certificate with Guide, HOD, and Examiner signatures
│   ├── acknowledgement.tex  # Formal acknowledgements to guide, HOD, institute, and NMC
│   ├── abstract.tex         # Comprehensive technical and policy abstract with keywords
│   ├── introduction.tex     # Chapter 1: Aim, Motivation, Scope, Objectives, Organization
│   ├── literature_review.tex# Chapter 2: Related Work, Existing Systems, Comparison, Gaps
│   ├── system_architecture.tex # Chapter 3: Problem Definition, Methodology, TikZ Diagrams, Algorithm
│   ├── requirements.tex     # Chapter 4: Hardware, Software, Functional & Non-Functional Specs
│   ├── high_level_design.tex# Chapter 5: Relational ERD, Level 0/1 DFD, UML Diagrams
│   ├── experimental_setup.tex # Chapter 6: Datasets, Preprocessing, 4 Protocols, Metrics
│   ├── results_evaluation.tex# Chapter 7: Results, Test Cases, GUI Screenshots, Cost Analysis
│   ├── project_planning.tex # Chapter 8: 16-Week Plan, Milestones, TikZ Gantt Chart
│   ├── conclusion.tex       # Chapter 9: Conclusions, Limitations, Future Scope
│   └── appendices.tex       # Appendices A--D: Plagiarism status, Base papers, Tools, Publications
├── figures/                 # Supporting figures, TikZ diagrams, screenshots, and placeholders
│   ├── architecture/        # TikZ system architecture diagram
│   ├── diagrams/            # TikZ workflows, K-Means clustering plots, SHAP attributions
│   ├── screenshots/         # Real high-resolution UI screenshots from the actual implementation
│   └── placeholders/        # Standardized placeholder images and fallback boxes
└── tables/                  # Dedicated directory for external table components (if needed)
```

---

## 2. Compilation Instructions

The report can be compiled using standard `latexmk`, `pdflatex`, or via cloud \LaTeX{} editors such as **Overleaf**.

### Local Compilation (pdflatex & bibtex sequence)

To resolve all cross-references, table of contents, list of figures, list of graphs, list of tables, and IEEE citations, execute the following sequence from within the `report/` directory:

```bash
cd report

# First pass: Generate auxiliary files
pdflatex main.tex

# Bibliography pass: Generate citation references
bibtex main

# Second pass: Resolve cross-references and citations
pdflatex main.tex

# Third pass: Finalize Table of Contents, Lists, and page numbering
pdflatex main.tex
```

### Automated Compilation (latexmk)

If `latexmk` is installed:

```bash
cd report
latexmk -pdf -synctex=1 -interaction=nonstopmode main.tex
```

### Overleaf / Cloud LaTeX

1. Zip the entire `report/` folder:
   ```powershell
   Compress-Archive -Path report\* -DestinationPath vendormap_stage2_report.zip
   ```
2. In Overleaf, create a **New Project** $\to$ **Upload Project**, and select `vendormap_stage2_report.zip`.
3. Set the compiler to **pdfLaTeX** and the main document to `main.tex`.
4. Click **Recompile**.

---

## 3. How to Replace Placeholder Images

Whenever a real output screenshot or certificate becomes available, replace the placeholder as follows:

### Method A: Replacing Reusable LaTeX Placeholder Macros (`\placeholderbox`)
In files such as `chapters/results_evaluation.tex` or `chapters/appendices.tex`, placeholders are rendered using:
```latex
\placeholderbox{Title}{Description}{Action Required}
```
To replace this with an actual image file (e.g., `figures/screenshots/my_screenshot.png`), simply replace the macro call with standard \LaTeX{} figure code:
```latex
\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.9\linewidth]{figures/screenshots/my_screenshot.png}
    \caption{Description of the screenshot.}
    \label{fig:my_screenshot}
\end{figure}
```

### Method B: Replacing Placeholder PNG Files
In `figures/placeholders/`, several placeholder images exist (e.g., `ui_whatsapp_bot_placeholder.png`, `confusion_matrix_placeholder.png`). Replace the PNG file directly with your actual screenshot having the exact same filename.

---

## 4. Where to Edit Student and Guide Details

All student, guide, and institute details are centralized in the following front-matter files:

1. **Title Page (`chapters/titlepage.tex`):**
   - Lines 18--25: Student Names, Seat Numbers, and Roll Numbers.
   - Lines 30--31: Project Guide Name and Designation (`Prof. Vidya R. More`).
   - Lines 34--43: Department and Institute details (`KKWIEER, Nashik-3`).

2. **Certificate (`chapters/certificate.tex`):**
   - Lines 13--20: Student Names and PRN / Roll Numbers.
   - Lines 31--36: Signatures for Project Guide and Head of Department (`Prof. Dr. P. D. Bhamre`).
   - Lines 40--45: Placeholders for External Examiner and Principal / Director signatures.

3. **Acknowledgement (`chapters/acknowledgement.tex`):**
   - Lines 32--38: Student sign-off block.

4. **Appendix D (`chapters/appendices.tex`):**
   - Publication author listing and acceptance certificates.

---

## 5. How to Update the Bibliography

The bibliography file `report/references.bib` contains 18 verified academic papers and statutory citations.

- Follow standard BibTeX formatting (`@article`, `@book`, `@inproceedings`, `@misc`).
- Include verified authors, publication titles, journals, volume, pages, year, and DOI.
- Cite entries in the text using `\cite{citation_key}`.
- Re-run `bibtex main` followed by `pdflatex main.tex` twice after modifying `references.bib`.

---

## 6. Checklist: What Still Needs to Be Supplied Manually

Before the final bound submission and institutional defense, the project team must supply:

1. **Plagiarism Certificate (Appendix A):**
   - Obtain the official plagiarism similarity report from the project guide (Prof. Vidya R. More).
   - Insert the counter-signed plagiarism certificate in `chapters/appendices.tex`.
2. **External Examiner Signature Date (Certificate):**
   - Fill in the actual defense date and obtain physical signatures on `chapters/certificate.tex`.
3. **Class Division / Roll Numbers:**
   - Double-check class division roll numbers on the Title Page and Certificate.
4. **Conference Acceptance Certificate (Appendix D):**
   - Insert the scanned copy of the conference acceptance notification or presentation certificate once issued.
5. **WhatsApp Real Screenshots (Chapter 7):**
   - If live Meta Cloud API message delivery is demonstrated during defense, insert actual mobile screenshots into `figures/screenshots/` and update Fig.~\ref{fig:ph_whatsapp}.
