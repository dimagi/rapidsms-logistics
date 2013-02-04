from rapidsms.utils.modules import try_import

def get_func(func_name):
    mod = func_name[0:func_name.rindex(".")]
    contact_module = try_import(mod)
    if contact_module is None:
        raise ImportError("Contact generator module %s is not defined." % mod)
    func = func_name[func_name.rindex(".") + 1:]
    if not hasattr(contact_module, func):
        raise ImportError("No function %s in module %s." %
                        (func, mod))
    return getattr(contact_module, func)
