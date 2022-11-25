def main(trans, webhook, params):
    try:
        if trans.user:
            hist = trans.get_history()
            if (hist):
                return {
                          'userid'     : trans.security.encode_id(trans.user.id), 
                          'username'   : trans.user.username, 
                          'email'      : trans.user.email, 
                          'history'    : trans.security.encode_id(hist.id), 
                          'historyname': hist.name
                       }
            else:
                return {'error': 'No history to export'}
        else:
            return {'error': "User not logged in"}
    except:
        return {'error': sys.exc_info()[0]}
