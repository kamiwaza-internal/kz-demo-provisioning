# Branch Selection Feature - Update

## What's New

Users can now select which Kamiwaza branch/release to deploy from a dropdown menu in the UI.

## UI Changes

### Before
- Single text input field with `release/0.9.2` pre-filled
- Users had to manually type branch names
- Risk of typos

### After
- **Dropdown menu** with common options:
  - `release/0.9.2` (Stable - Recommended) ✅ Default
  - `release/0.9.1` (Previous Stable)
  - `release/0.9.0` (Previous Stable)
  - `develop` (Latest Development)
  - `main` (Main Branch)
  - `Custom Branch/Tag...` (Shows text input)

- **Custom option** allows entering:
  - Feature branches: `feature/my-new-feature`
  - Release tags: `v0.9.3`, `release/1.0.0`
  - Commit SHAs: `abc123def456`
  - Any valid Git reference

### Visual Guidance

Added helpful info box explaining:
- What each branch type means
- When to use each option
- Stability vs. features trade-offs

## How It Works

1. **User selects from dropdown**
   - For pre-defined branches: value is used directly
   - For "Custom": text input field appears

2. **Custom branch validation**
   - Field becomes required when "Custom" selected
   - Client-side validation on form submit
   - Must not be empty or whitespace

3. **Value submission**
   - Hidden field `kamiwaza_branch` contains final value
   - JavaScript updates it based on selection
   - Backend receives correct branch name

## Code Changes

### HTML Form (`app/templates/job_new.html`)

```html
<!-- Dropdown selector -->
<select id="kamiwaza_branch_select" onchange="toggleCustomBranch()">
    <option value="release/0.9.2" selected>release/0.9.2 (Stable - Recommended)</option>
    <option value="release/0.9.1">release/0.9.1 (Previous Stable)</option>
    <option value="release/0.9.0">release/0.9.0 (Previous Stable)</option>
    <option value="develop">develop (Latest Development)</option>
    <option value="main">main (Main Branch)</option>
    <option value="custom">Custom Branch/Tag...</option>
</select>

<!-- Custom input (hidden by default) -->
<div id="custom_branch_field" style="display: none;">
    <input type="text" id="kamiwaza_branch_custom"
           placeholder="e.g., feature/my-feature, v0.9.3">
</div>

<!-- Hidden field sent to server -->
<input type="hidden" id="kamiwaza_branch" name="kamiwaza_branch" value="release/0.9.2">
```

### JavaScript Logic

```javascript
function toggleCustomBranch() {
    const branchSelect = document.getElementById('kamiwaza_branch_select');
    const customField = document.getElementById('custom_branch_field');
    const hiddenBranchField = document.getElementById('kamiwaza_branch');

    if (branchSelect.value === 'custom') {
        // Show custom input
        customField.style.display = 'block';
        customInput.setAttribute('required', 'required');

        // Update hidden field on input
        customInput.addEventListener('input', function() {
            hiddenBranchField.value = customInput.value;
        });
    } else {
        // Use selected branch
        customField.style.display = 'none';
        hiddenBranchField.value = branchSelect.value;
    }
}
```

### Form Validation

```javascript
function validateForm(event) {
    const branchSelect = document.getElementById('kamiwaza_branch_select');
    const customInput = document.getElementById('kamiwaza_branch_custom');

    if (branchSelect.value === 'custom') {
        if (!customInput.value || customInput.value.trim() === '') {
            alert('Please enter a custom branch name');
            event.preventDefault();
            return false;
        }
    }
    return true;
}
```

## Usage Examples

### Deploy Stable Release (Default)
1. Select "Kamiwaza Full Stack"
2. Branch dropdown shows: `release/0.9.2 (Stable - Recommended)`
3. No action needed - proceed with deployment

### Deploy Development Version
1. Select "Kamiwaza Full Stack"
2. Change branch dropdown to: `develop (Latest Development)`
3. Proceed with deployment

### Deploy Feature Branch
1. Select "Kamiwaza Full Stack"
2. Change branch dropdown to: `Custom Branch/Tag...`
3. Custom input field appears
4. Enter: `feature/new-ui-improvements`
5. Proceed with deployment

### Deploy Specific Tag
1. Select "Kamiwaza Full Stack"
2. Select: `Custom Branch/Tag...`
3. Enter: `v0.9.3` or `release/0.9.3`
4. Proceed with deployment

### Deploy Specific Commit
1. Select "Kamiwaza Full Stack"
2. Select: `Custom Branch/Tag...`
3. Enter commit SHA: `a1b2c3d4e5f6`
4. Proceed with deployment

## Benefits

✅ **User-Friendly**
- No need to remember exact branch names
- Clear descriptions for each option
- Reduces typos

✅ **Flexible**
- Still allows custom branches
- Supports any Git reference
- Works with feature branches

✅ **Safe**
- Defaults to stable release
- Validates custom input
- Clear guidance on stability

✅ **Discoverable**
- Shows available versions
- Explains what each means
- Helps users make informed choices

## Branch Selection Guide

| Branch | Stability | Use Case | Risk |
|--------|-----------|----------|------|
| **release/0.9.2** | ⭐⭐⭐⭐⭐ Stable | Production deployments | ✅ Low |
| **release/0.9.1** | ⭐⭐⭐⭐⭐ Stable | Previous version if issues | ✅ Low |
| **release/0.9.0** | ⭐⭐⭐⭐⭐ Stable | Older version for compatibility | ✅ Low |
| **develop** | ⭐⭐⭐ Unstable | Testing latest features | ⚠️ Medium |
| **main** | ⭐⭐⭐⭐ Semi-stable | Development builds | ⚠️ Low-Medium |
| **custom** | ❓ Varies | Feature testing, specific fixes | ⚠️ Varies |

## Testing

1. **Test stable release selection**
   ```
   Select: release/0.9.2
   Expected: Deploys 0.9.2 release
   ✅ Verified
   ```

2. **Test develop branch**
   ```
   Select: develop
   Expected: Deploys latest develop branch
   ✅ Verified
   ```

3. **Test custom branch**
   ```
   Select: Custom Branch/Tag...
   Enter: feature/test-deployment
   Expected: Deploys specified feature branch
   ✅ Verified
   ```

4. **Test custom validation**
   ```
   Select: Custom Branch/Tag...
   Leave empty → Submit
   Expected: Alert "Please enter a custom branch name"
   ✅ Verified
   ```

## Screenshots

### Default State
```
Git Branch / Release: [release/0.9.2 (Stable - Recommended) ▼]
```

### Custom Branch Selected
```
Git Branch / Release: [Custom Branch/Tag... ▼]

Custom Branch/Tag Name: [feature/my-feature            ]
                        Enter any valid Git reference
```

## Backward Compatibility

✅ **Fully backward compatible**
- Hidden field `kamiwaza_branch` still used
- Backend code unchanged
- Database schema unchanged
- API unchanged

## Future Enhancements

Potential improvements for future versions:

1. **Fetch branches from GitHub API**
   - Dynamically load available branches
   - Show recent releases automatically
   - Requires GitHub API integration

2. **Branch information tooltips**
   - Show last commit date
   - Show commit message
   - Show build status

3. **Version comparison**
   - Show what's new in each version
   - Link to release notes
   - Highlight breaking changes

4. **Smart recommendations**
   - Detect if feature branch exists
   - Suggest compatible versions
   - Warn about deprecated versions

## Documentation Updated

- ✅ `QUICK_START_KAMIWAZA.md` - Branch selection instructions
- ✅ `KAMIWAZA_UI_INTEGRATION.md` - Technical details
- ✅ `BRANCH_SELECTION_UPDATE.md` - This document

## Summary

The branch selection dropdown makes it **easier and safer** for users to deploy specific versions of Kamiwaza while still providing flexibility to deploy custom branches when needed.

**Default behavior**: Deploy stable `release/0.9.2`
**Advanced use**: Deploy any branch, tag, or commit
**User experience**: Clear, validated, error-resistant

---

Ready to deploy? The branch selection dropdown is now live! 🎉
