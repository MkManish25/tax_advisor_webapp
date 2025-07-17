"""
Tax Calculation Engine for Indian Tax Regimes (FY 2024-25).
Contains functions to calculate tax for both Old and New Regimes.
"""

def calculate_old_regime_tax(net_taxable_income):
    """Calculates tax liability under the Old Tax Regime."""
    tax = 0
    if net_taxable_income <= 250000:
        tax = 0
    elif net_taxable_income <= 500000:
        tax = (net_taxable_income - 250000) * 0.05
    elif net_taxable_income <= 1000000:
        tax = 12500 + (net_taxable_income - 500000) * 0.20
    else:
        tax = 112500 + (net_taxable_income - 1000000) * 0.30
    
    # Add 4% cess
    cess = tax * 0.04
    return tax + cess

def calculate_new_regime_tax(net_taxable_income):
    """Calculates tax liability under the New Tax Regime (Default)."""
    tax = 0
    if net_taxable_income <= 300000:
        tax = 0
    elif net_taxable_income <= 600000:
        tax = (net_taxable_income - 300000) * 0.05
    elif net_taxable_income <= 900000:
        tax = 15000 + (net_taxable_income - 600000) * 0.10
    elif net_taxable_income <= 1200000:
        tax = 45000 + (net_taxable_income - 900000) * 0.15
    elif net_taxable_income <= 1500000:
        tax = 90000 + (net_taxable_income - 1200000) * 0.20
    else:
        tax = 150000 + (net_taxable_income - 1500000) * 0.30
        
    # Add 4% cess
    cess = tax * 0.04
    return tax + cess

def get_net_taxable_income_old(data):
    """Calculates net taxable income for the Old Regime after deductions."""
    # Assuming data is a dictionary with all financial fields
    gross = float(data.get('gross_salary', 0))
    deductions = (
        float(data.get('standard_deduction', 0)) +
        float(data.get('professional_tax', 0)) +
        float(data.get('deduction_80c', 0)) +
        float(data.get('deduction_80d', 0))
        # Add HRA calculation here if needed
    )
    return max(0, gross - deductions)

def get_net_taxable_income_new(data):
    """Calculates net taxable income for the New Regime."""
    gross = float(data.get('gross_salary', 0))
    # Only standard deduction is available
    deductions = float(data.get('standard_deduction', 0))
    return max(0, gross - deductions) 