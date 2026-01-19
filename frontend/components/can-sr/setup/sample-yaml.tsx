export const SAMPLE_YAML = `# Example simplified criteria configuration (YAML)

# Include: grab all key columns from the uploaded CSV for title/abstract screening
include:
  - Title
  - Abstract
  - Keywords
  - Journal
  - Type
  - Type of Work
  - Notes
  - Year

# Define title/abstract screening criteria
# The format is:
#   Question 1:
#     possible answer 1: |
#       <description>
#     possible answer 2: |
#       ...
#   Question 2:
#     ...

criteria:
  "Is this article primary research?":
    "Yes - primary research" : |
        Primary research: a study where data is collected and/or analyzed by the authors.
    "No - systematic review meta-analysis or rapid review" : |
        Select this option if this is an evidence synthesis such as systematic review, meta-analysis, rapid review and scoping review

# Define additional criteria for fulltext screening (additional to title/abstract)
l2_criteria:
  "Does this study and case report or case series have more than 10 cases?":
    "Yes" : |
      This case report or case series covers more than 10 cases 
    "No (exclude)" : | 
      This case report or case series covers less than 10 cases

# Extraction parameters: one generic parameter to extract
# The format is:
#   Parameter Question 1:
#     parameter 1: |
#       <description>
#     parameter 2: |
#       ...
#   Parameter Question 2:
#     ...
parameters:
  "What Epidemiological Parameters are reported in this study?":
    "Attack Rate": |
      Attack rate is the proportion of an at-risk population that contracts the disease during a specified time interval. It is often reported as a percentage or as rate e.g. 52 people per 10,000 people. 
  "What relative contributions are reported in this study?":
    "Human to Human": |
      Proportion of cases that are likely be from human-to human transmission.
`
