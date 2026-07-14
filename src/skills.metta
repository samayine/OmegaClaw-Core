(= (getSkills)
   (;PATIENT DATA — always fetch patient data first before answering:
    "- List all patients with summary (use this first if no patient_id given): list_patients"
    "- Get full patient data by ID: get_patient patient_id"
    "- Get biomarker and PC trends over time: get_longitudinal patient_id"
    "  Use get_longitudinal when asked about trends, changes over time, progress, or treatment response"
    ;MEMORY — query ChromaDB for PC clinical knowledge (diseases, mechanisms, interventions):
    "- Query long-term embedding memory for PC knowledge: query string"
    "- Remember a clinical insight for future reference: remember string"
    "- Search history for episodes around a timestamp: episodes time_string"
    "- Pin working state to track reasoning progress: pin string"
    ;REASONING — use PLN to combine biomarker signals with confidence:
    "- Execute MeTTa or PLN expression: metta sexpression"
    "PLN example — chain biomarker evidence with truth values:"
    "metta (|~ ((Implication (Inheritance $patient HighPC1) (Inheritance $patient CardioRisk)) (stv 0.85 0.90))"
    "          ((Inheritance patient42 HighPC1) (stv 0.95 0.85)))"
    "NAL example: metta (|- ((--> patient42 elevated_PC1) (stv 1.0 0.95))"
    "                      ((--> elevated_PC1 cardio_risk) (stv 0.85 0.90)))"
    ;COMMUNICATION — one send per turn, only when ready with final answer:
    "- Send final clinical answer to clinician: send string"))


(= (read-file $file)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (read_file_to_string $file $content ()))
          $content))

(= (write-file $file $str)
   (progn (translatePredicate (open $file write $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (close $Out))
          WRITE-FILE-SUCCESS))

(= (append-file $file $str)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (open $file append $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (nl $Out)),
          (translatePredicate (close $Out))
          APPEND-FILE-SUCCESS))

(= (get_patient $patient_id)
   (py-call (alis_data.get_patient $patient_id)))

(= (list_patients)
   (py-call (alis_data.list_patients)))

(= (get_longitudinal $patient_id)
   (py-call (alis_data.get_longitudinal $patient_id)))

(= (tavily-search $query)
   (py-call (agentverse.tavily_search $query)))

(= (technical-analysis $ticker)
   (py-call (agentverse.technical_analysis $ticker)))

!(import_prolog_functions_from_file (library OmegaClaw-Core ./src/skills.pl) (shell first_char gc read_file_tail))

(= (metta $str)
   (let $code (sread $str)
        (repr (swrite (eval $code)))))

(= (pin $x)
   PIN-SUCCESS)
