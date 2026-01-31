# PRD: Skaelvox VM Evolver - Bug Fixes & Quality Improvements

## Introduction

The Skaelvox VM Evolver is an Azure VM cost optimization CLI tool with AI-driven analysis. A comprehensive code review has identified several bugs, security concerns, and improvement opportunities that need to be addressed to bring the tool to production quality. This PRD covers critical bug fixes, code quality improvements, and foundational enhancements.

## Background

The tool is functional but has the following categories of issues:
- **Bugs**: Logic errors in memory calculation, type mismatches, shell injection risk, recursive stack overflow, incorrect CLI parameter wiring
- **Code Quality**: No test suite, deprecated API usage, silent error swallowing, hardcoded data that should be dynamic
- **Robustness**: No retry logic for API calls, no pagination handling, no rate limiting for concurrent requests

## Goals

- Fix all identified bugs to ensure correct behavior
- Eliminate security vulnerabilities (shell injection)
- Add a foundational test suite for critical paths
- Replace deprecated Python APIs
- Improve error handling and resilience for Azure API interactions
- Enable the interactive menu to loop properly after command execution

## User Stories

**Story 1: As a user, I want accurate memory utilization metrics so that rightsizing recommendations are correct**
- [ ] Fix inverted max memory calculation in `azure_client.py` (max usage = min available, not max available)
- [ ] Fix `any([vm.avg_cpu, vm.avg_memory])` to use `is not None` checks (0.0 is a valid metric value)
- [ ] Add unit tests for memory conversion logic
- [ ] Code checks pass

**Story 2: As a user, I want the interactive menu to work correctly without crashes**
- [ ] Fix recursive `interactive_menu()` call to use a loop instead (prevents stack overflow in long sessions)
- [ ] Fix `run_interactive_check_capacity()` passing `--sku` which is not a valid parameter for `check-capacity`
- [ ] Fix interactive menu to loop back after command execution
- [ ] Code checks pass

**Story 3: As a developer, I want the codebase free of security vulnerabilities**
- [ ] Replace `shell=True` in `subprocess.run` for Azure CLI auto-detection in `availability_checker.py`
- [ ] Use `subprocess.run(["az", "account", "show", ...])` with list arguments instead
- [ ] Code checks pass

**Story 4: As a developer, I want consistent and correct data handling across modules**
- [ ] Fix `"virtualMachines" in rec.impacted_field.lower()` case mismatch in `azure_client.py:370`
- [ ] Fix `savings_percent` variable being assigned `annualSavingsAmount` (amount, not percent) in `azure_client.py:388`
- [ ] Fix self-referencing region alternative: `southcentralus` lists itself in `config.py:169`
- [ ] Fix `vm_name = parts[-1]` when resource_id could produce `['']` in `azure_client.py:375`
- [ ] Code checks pass

**Story 5: As a developer, I want the codebase to use non-deprecated APIs**
- [ ] Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` in `azure_client.py`, `analysis_engine.py`, and `availability_checker.py`
- [ ] Ensure all timestamp comparisons use timezone-aware datetimes
- [ ] Code checks pass

**Story 6: As a user, I want reliable Azure API interactions that handle transient failures**
- [ ] Add retry logic with exponential backoff to `PricingClient` HTTP calls
- [ ] Add pagination handling for Azure Retail Prices API (`NextPageLink`)
- [ ] Add basic rate limiting to `ThreadPoolExecutor` concurrent API calls
- [ ] Code checks pass

**Story 7: As a developer, I want a test suite to prevent regressions**
- [ ] Create `tests/` directory with pytest configuration
- [ ] Add unit tests for `_extract_generation()` SKU name parsing
- [ ] Add unit tests for `_extract_family()` VM family extraction
- [ ] Add unit tests for `_calculate_sku_score()` scoring logic
- [ ] Add unit tests for `format_currency()` and `format_percent()` helpers
- [ ] Add unit tests for `PricingClient` cache behavior (mocked HTTP)
- [ ] Add unit tests for memory byte-to-percent conversion
- [ ] All tests pass with `pytest`

**Story 8: As a user, I want dynamic memory lookup instead of hardcoded SKU mappings**
- [ ] Replace hardcoded `_get_vm_total_memory_bytes()` dictionary with Azure SKU API lookup
- [ ] Use the already-cached SKU data from `_get_cached_skus()` to resolve memory
- [ ] Fall back to hardcoded map only when SKU cache is not available
- [ ] Code checks pass

## Functional Requirements

- FR-1: Fix max memory usage calculation to use minimum of "Available Memory Bytes" (not maximum)
- FR-2: Replace `any([vm.avg_cpu, vm.avg_memory])` with proper `is not None` checks
- FR-3: Convert recursive `interactive_menu()` to a `while True` loop
- FR-4: Fix `run_interactive_check_capacity()` to pass correct `--vcpus`/`--memory` parameters
- FR-5: Remove `shell=True` from subprocess calls; use list-form arguments
- FR-6: Fix case-insensitive string comparison for `impacted_field`
- FR-7: Rename `savings_percent` variable to `annual_savings_amount` or fix the data source
- FR-8: Remove `southcentralus` from its own alternative regions list
- FR-9: Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)`
- FR-10: Add retry decorator/logic with exponential backoff to HTTP calls
- FR-11: Handle `NextPageLink` in Azure Pricing API pagination
- FR-12: Create pytest test suite with >80% coverage on utility functions
- FR-13: Use SKU cache for memory resolution instead of hardcoded dictionary
- FR-14: Add `PricingClient` context manager support (`__enter__`/`__exit__`)

## Non-Goals

- No new features or CLI commands (this is strictly bug fixes and quality improvements)
- No UI/UX changes to the Rich terminal output
- No changes to the AI analysis prompts or Claude integration
- No changes to the Skaelvox generation evolution algorithm logic
- No migration to asyncio (future enhancement)
- No HTML/PDF report generation (separate PRD)
- No CI/CD pipeline setup (separate PRD)

## Technical Considerations

- Python 3.9+ compatibility must be maintained (timezone.utc is available in 3.9)
- All Azure SDK interactions should gracefully degrade when APIs are unavailable
- Thread-safety must be preserved in all cached data access
- Retry logic should use tenacity or a simple custom decorator (avoid adding heavy dependencies)
- Tests should use unittest.mock for Azure SDK and HTTP mocking
- The `sys.argv` mutation pattern in interactive mode is fragile but changing it is out of scope for this PRD

## Success Metrics

- Zero known bugs remaining from the identified list
- All unit tests pass
- No Python deprecation warnings when run on Python 3.12+
- Memory metrics accurately reflect used percentage (not inverted)
- Interactive menu works in sessions lasting 50+ command selections without stack overflow
- Pricing API handles paginated results for SKUs with many regional prices

## Open Questions

- Should we add `tenacity` as a dependency for retry logic, or implement a simple custom retry decorator?
  - Decision: Use a simple custom retry decorator to minimize dependencies
- Should the `sys.argv` mutation pattern in interactive mode be refactored to use Typer's programmatic API?
  - Decision: Out of scope for this PRD, but noted as a future improvement

---

_This PRD is ready for conversion to JSON stories for Ralph Copilot._
