const jwt = require('jsonwebtoken');
const User = require('../models/User');

// ── helpers ───────────────────────────────────────────────────────────────────
function buildToken(userId) {
  return jwt.sign({ userId }, process.env.JWT_SECRET, { expiresIn: '7d' });
}

function setTokenCookie(res, token) {
  res.cookie('token', token, {
    httpOnly: true,
    secure:   process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge:   7 * 24 * 60 * 60 * 1000,   // 7 days — matches token expiry
  });
}

function userPayload(user) {
  return {
    _id:       user._id,
    name:      user.name,
    email:     user.email,
    role:      user.role,
    skillTags: user.skillTags,
    teamIds:   user.teamIds,
    createdAt: user.createdAt,
    updatedAt: user.updatedAt,
  };
}

// ── POST /api/auth/register ───────────────────────────────────────────────────
const register = async (req, res, next) => {
  try {
    const {
      // New UI sends firstName + lastName separately
      firstName, lastName,
      // Old / API callers send a combined name
      name,
      email, password, role, skillTags,
    } = req.body;

    // Resolve display name from either convention
    const displayName = name?.trim() ||
      [firstName?.trim(), lastName?.trim()].filter(Boolean).join(' ');

    if (!displayName || !email || !password) {
      return res.status(400).json({
        success: false,
        message: 'Name (or first + last name), email and password are required.',
      });
    }

    const existingUser = await User.findOne({ email: email.toLowerCase() });
    if (existingUser) {
      return res.status(400).json({ success: false, message: 'Email already registered.' });
    }

    const user = new User({
      name:         displayName,
      email:        email.toLowerCase(),
      passwordHash: password,           // User model pre-save hook hashes this
      role:         role || 'developer',
      skillTags:    Array.isArray(skillTags) ? skillTags : [],
    });

    await user.save();

    const token = buildToken(user._id);
    setTokenCookie(res, token);

    return res.status(201).json({
      success: true,
      data:    { user: userPayload(user), token },
    });
  } catch (error) {
    next(error);
  }
};

// ── POST /api/auth/login ──────────────────────────────────────────────────────
const login = async (req, res, next) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({
        success: false,
        message: 'Email and password are required.',
      });
    }

    const user = await User.findOne({ email: email.toLowerCase() });
    if (!user) {
      return res.status(401).json({ success: false, message: 'Invalid email or password.' });
    }

    const isMatch = await user.comparePassword(password);
    if (!isMatch) {
      return res.status(401).json({ success: false, message: 'Invalid email or password.' });
    }

    const token = buildToken(user._id);
    setTokenCookie(res, token);

    return res.json({
      success: true,
      data:    { user: userPayload(user), token },
    });
  } catch (error) {
    next(error);
  }
};

// ── GET /api/auth/me ──────────────────────────────────────────────────────────
const getMe = async (req, res) => {
  return res.json({
    success: true,
    data:    { user: userPayload(req.user) },
  });
};

// ── POST /api/auth/logout ─────────────────────────────────────────────────────
const logout = (req, res) => {
  res.clearCookie('token');
  return res.json({ success: true, message: 'Logged out successfully.' });
};

module.exports = { register, login, getMe, logout };