const authService = require('../services/authService');
const { AUTH } = require('../constants');
const handleError = require('../utils/handleError');

function setTokenCookie(res, token) {
  res.cookie('token', token, {
    httpOnly: true,
    secure:   process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge:   AUTH.COOKIE_MAX_AGE,
  });
}

// @route   POST /api/auth/register
// @access  Public
const register = async (req, res, next) => {
  try {
    const { user, token } = await authService.register(req.body);
    setTokenCookie(res, token);
    return res.status(201).json({ success: true, data: { user, token } });
  } catch (error) { handleError(error, res, next); }
};

// @route   POST /api/auth/login
// @access  Public
const login = async (req, res, next) => {
  try {
    const { user, token } = await authService.login(req.body.email, req.body.password);
    setTokenCookie(res, token);
    return res.json({ success: true, data: { user, token } });
  } catch (error) { handleError(error, res, next); }
};

// @route   GET /api/auth/me
// @access  Private
const getMe = (req, res) => {
  return res.json({ success: true, data: { user: authService.userPayload(req.user) } });
};

// @route   POST /api/auth/logout
// @access  Private
const logout = (req, res) => {
  res.clearCookie('token');
  return res.json({ success: true, message: 'Logged out successfully.' });
};

module.exports = { register, login, getMe, logout };
