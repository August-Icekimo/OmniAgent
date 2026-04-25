## ADDED Requirements

### Requirement: Modular Skill Execution
The system must provide an extensible interface for executing specialized technical tasks.

#### Scenario: Skill Execution Request
- **WHEN** the Brain service calls the Skills Server via `POST /skill/execute` with a skill name and parameters
- **THEN** the Skills Server must route the request to the appropriate handler
- **AND** return a standardized JSON response containing the execution status and results.

### Requirement: Server Management (Cockpit)
The system must be able to query and manage HomeLab servers via the Cockpit API.

#### Scenario: Query Host Status
- **WHEN** the `cockpit` skill is called with `action: "status"`
- **THEN** it must return CPU, RAM, and Disk usage statistics from the target host.

#### Scenario: Restart System Service
- **WHEN** the `cockpit` skill is called with `action: "restart_service"` and a valid service name
- **THEN** it must authenticate to the Cockpit API
- **AND** trigger the service restart.

### Requirement: Network Management (Wake-on-LAN)
The system must be able to wake up computers on the local network.

#### Scenario: Send Magic Packet
- **WHEN** the `wake_on_lan` skill is called with a valid MAC address
- **THEN** it must broadcast a Magic Packet (UDP) to the local network to wake the device.

### Requirement: File Analysis (Vision & OCR)
The system must be able to extract and summarize information from various file types.

#### Scenario: PDF Analysis
- **WHEN** the `file_analyze` skill receives a PDF file
- **THEN** it must extract the text content and use the LLM to generate a summary.

#### Scenario: Image Analysis (Vision)
- **WHEN** the `file_analyze` skill receives an image
- **THEN** it must use a Vision-capable LLM (e.g., Claude Vision) to perform OCR and describe the image content.

#### Scenario: Spreadsheet Analysis
- **WHEN** the `file_analyze` skill receives an Excel file
- **THEN** it must read the sheets (up to a limit) and provide a structured summary of the data.
