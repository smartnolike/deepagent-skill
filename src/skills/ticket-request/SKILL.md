# Ticket Request Skill

For a resource request, identify the resource type and call `ticketing__get_resource_schema`.
Never guess required fields. Collect multiple user-provided fields in a turn, retain the latest value,
ask naturally for missing fields, and do not display the raw JSON Schema. Before creation, call
`ticketing__validate_ticket_params`; only call `ticketing__create_ticket` after valid validation.
