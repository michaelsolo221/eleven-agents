# New Claims Lodgement Agent instead of modifying Support Agent

We are building a CGU insurance claims lodgement channel (phone + WhatsApp). The existing Support Agent is a generic WhatsApp helpdesk bot with a different greeting, different goal (troubleshooting/FAQ), and different guardrails. Rather than modifying it, we create a new agent — Claims Lodgement Officer — with its own prompt, first message, guardrails, and interaction model (guided flow + express lodgement). The two agents serve fundamentally different purposes and merging them would create a confusing hybrid.
