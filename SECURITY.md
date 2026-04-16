# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.48.x  | :white_check_mark: |
| < 0.48  | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in GEODE, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please use one of these methods:

1. **GitHub Security Advisories**: Report via [GitHub's private vulnerability reporting](https://github.com/mangowhoiscloud/geode/security/advisories/new)
2. **Email**: Contact the maintainers directly (see repository profile)

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 1 week
- **Fix Release**: Depends on severity, typically within 2 weeks for critical issues

### Scope

The following are in scope:

- Code execution vulnerabilities in the CLI or serve daemon
- API key exposure through logging or error messages
- Injection attacks via tool handlers or MCP integration
- Authentication bypass in OAuth credential readers
- Sandbox escape in file/process tools

The following are out of scope:

- Vulnerabilities in third-party LLM APIs (Anthropic, OpenAI, ZhipuAI)
- Social engineering attacks
- Denial of service through normal API rate limiting
