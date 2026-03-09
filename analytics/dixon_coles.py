# analytics/dixon_coles.py — koreksi probabilitas skor rendah
def tau(x, y, lambda_, mu, rho):
    """
    Faktor koreksi untuk skor 0-0, 1-0, 0-1, 1-1.
    rho negatif = korelasi negatif (tim yang kalah bermain lebih hati-hati).
    """
    if x == 0 and y == 0:
        return 1 - lambda_ * mu * rho
    elif x == 0 and y == 1:
        return 1 + lambda_ * rho
    elif x == 1 and y == 0:
        return 1 + mu * rho
    elif x == 1 and y == 1:
        return 1 - rho
    return 1.0