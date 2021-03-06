import ConfigParser


class Person(object):
    def __init__(self, datascope, name):
        self.datascope = datascope
        self.name = name

    def __repr__(self):
        return '<Person: %s>' % self.name.title()

    @property
    def is_active(self):
        return self.after_tax_target_salary > 0

    @property
    def is_partner(self):
        return self.ownership > 0

    @property
    def ownership(self):
        try:
            return self.datascope.config.getfloat('ownership', self.name)
        except ConfigParser.NoOptionError:
            return 0.0

    @property
    def after_tax_target_salary(self):
        """This is on a per month basis, but includes biweekly salary as well
        as annual bonus and dividends. If the target take home pay is not
        specified, then we estimate the target take home pay from the monthly
        after tax pay and the number of months of after tax bonus expected at
        the end of the year.
        """
        default_pay = self.datascope.after_tax_salary
        default_pay *= (1 + self.datascope.n_months_after_tax_bonus/12)
        try:
            pay = self.datascope.config.getfloat('take home pay', self.name)
        except (ConfigParser.NoOptionError, ValueError):
            pay = default_pay
        return pay

    def fraction_dividends(self):
        """Fraction of profits that come in the form of a dividend"""
        return self.datascope.fraction_profit_for_dividends * self.ownership

    def fraction_bonus(self):
        """Fraction of profits that come in the form of a bonus"""
        return (1.0-self.datascope.fraction_profit_for_dividends) /\
            self.datascope.n_people

    def net_fraction_of_profits(self):
        """Net fraction of all profits"""
        return self.fraction_dividends() + self.fraction_bonus()

    def after_tax_target_salary_from_bonus_dividends(self):
        return self.after_tax_target_salary - self.datascope.after_tax_salary

    def after_tax_salary_from_bonus(self):
        return self.fraction_bonus() *\
            self.datascope.after_tax_target_profit()

    def after_tax_salary_from_dividends(self):
        return self.fraction_dividends() *\
            self.datascope.after_tax_target_profit()

    def after_tax_salary(self):
        return (
            self.after_tax_salary_from_bonus() +
            self.after_tax_salary_from_dividends() +
            self.datascope.after_tax_salary
        )

    def before_tax_target_bonus_dividends(self):
        # only bonuses are taxed at tax rate.
        target_bonus = \
            self.after_tax_salary_from_bonus() / (1 - self.datascope.tax_rate)
        target_dividends = self.after_tax_salary_from_dividends()
        return target_bonus + target_dividends
